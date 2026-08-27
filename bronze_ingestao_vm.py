"""
Ingestão Bronze — SUS+ Inteligente (Compute Instance + cron)

Mesma lógica do que tentamos empacotar como OCI Function, mas rodando
como script Python comum numa Compute Instance — sem Docker, sem
compilar nada, só `pip install` normal.

Autenticação: usa Instance Principal (a própria VM se autentica na OCI,
sem precisar de chave de API armazenada nela). Requer um Dynamic Group
+ Policy dando permissão de escrita no bucket (ver instruções de setup).

Agendamento: configurado via crontab na própria VM (não depende de
nenhum serviço OCI adicional).
"""

import json
import os
import requests
import duckdb
import pandas as pd
import oci


# --- Configuração ------------------------------------------------------
# UF, ANO e MESES podem ser sobrescritos via variáveis de ambiente,
# sem precisar editar o código. Os valores abaixo são o padrão (o mesmo
# recorte usado no MVP: SP, 2024, meses disponíveis na fonte do SIH).
UF = os.environ.get("SUS_UF", "SP")
ANO = int(os.environ.get("SUS_ANO", "2024"))
MESES = [int(m) for m in os.environ.get("SUS_MESES", "2,6,8,12").split(",")]

NAMESPACE = "grkdxjifyvni"
OUTPUT_BUCKET = "sus-inteligente-input"

CODIGO_UF = {
    "RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17,
    "MA": 21, "PI": 22, "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27,
    "SE": 28, "BA": 29, "MG": 31, "ES": 32, "RJ": 33, "SP": 35, "PR": 41,
    "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53,
}
LEITOS_URL = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/Leitos_SUS/Leitos_2024.csv"
STAGING_DIR = "/home/opc/sus_staging"
os.makedirs(STAGING_DIR, exist_ok=True)
# ------------------------------------------------------------------------


def get_object_storage_client():
    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    return oci.object_storage.ObjectStorageClient(config={}, signer=signer)


def upload_arquivo(client, caminho_local, object_name):
    with open(caminho_local, "rb") as f:
        client.put_object(NAMESPACE, OUTPUT_BUCKET, object_name, f)
    print(f"  upload OK -> oci://{OUTPUT_BUCKET}@{NAMESPACE}/{object_name}")


def bronze_sih(client):
    from pysus import sih

    print(f"[bronze/sih] baixando {UF} {ANO} — meses {MESES} ...")
    arquivos_brutos = [str(p) for p in sih(state=UF, year=ANO, month=MESES)]
    if not arquivos_brutos:
        raise FileNotFoundError("Nenhum mês do SIH disponível para o recorte configurado.")

    # Filtra só o grupo RD (AIH Reduzida — internações). A fonte às vezes
    # devolve outros grupos (ex.: SP — Serviços Profissionais) quando o RD
    # ainda não foi publicado pelo DATASUS para o período pedido — nesse
    # caso, é melhor falhar com uma mensagem clara do que processar dados
    # da estrutura errada.
    arquivos = [p for p in arquivos_brutos if os.path.basename(p).upper().startswith("RD")]
    grupos_encontrados = sorted({os.path.basename(p)[:2].upper() for p in arquivos_brutos})
    if not arquivos:
        raise FileNotFoundError(
            f"Grupo RD (internações) não disponível para {UF}/{ANO}/{MESES} — "
            f"a fonte só tinha o(s) grupo(s) {grupos_encontrados} publicado(s) até o momento. "
            f"Isso costuma significar que o DATASUS ainda não processou/publicou "
            f"as internações (RD) desse período — tente novamente mais tarde ou "
            f"ajuste os meses configurados."
        )
    if len(arquivos) < len(arquivos_brutos):
        print(f"  [AVISO] {len(arquivos_brutos) - len(arquivos)} arquivo(s) de outro grupo "
              f"({grupos_encontrados}) foram ignorados — usando só RD.")

    colunas = ["UF_ZI", "ANO_CMPT", "MES_CMPT", "MUNIC_RES", "MUNIC_MOV",
               "DT_INTER", "DT_SAIDA", "DIAS_PERM", "VAL_TOT", "IDADE",
               "SEXO", "DIAG_PRINC", "CNES"]
    lista_arquivos_sql = ", ".join(f"'{p}'" for p in arquivos)
    colunas_sql = ", ".join(colunas)
    codigo_uf = str(CODIGO_UF[UF])
    meses_sql = ", ".join(f"'{m:02d}'" for m in MESES)
    out_path = f"{STAGING_DIR}/sih_{UF}_{ANO}.parquet"

    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT {colunas_sql}
            FROM read_parquet([{lista_arquivos_sql}], union_by_name=True)
            WHERE SUBSTR(UF_ZI, 1, 2) = '{codigo_uf}'
              AND ANO_CMPT = '{ANO}'
              AND MES_CMPT IN ({meses_sql})
        ) TO '{out_path}' (FORMAT PARQUET)
    """)
    total = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    con.close()
    print(f"[bronze/sih] OK — {total} registros")
    upload_arquivo(client, out_path, f"bronze/sih/sih_{UF}_{ANO}.parquet")
    return total


def bronze_cnes(client, meta_registros=300):
    url = "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos"
    codigo_uf_alvo = CODIGO_UF[UF]
    registros_da_uf, offset_atual = [], 0
    assinatura_anterior = None

    print(f"[bronze/cnes] consultando API, filtrando localmente por UF={UF} ...")
    for _ in range(100):
        params = {"uf": UF, "codigo_uf": codigo_uf_alvo, "limit": 200, "offset": offset_atual}
        resp = None
        for tentativa in range(4):
            try:
                resp = requests.get(url, params=params, timeout=60)
                resp.raise_for_status()
                break
            except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError,
                    requests.exceptions.ReadTimeout) as e:
                espera = 2 ** tentativa  # 1s, 2s, 4s, 8s
                print(f"  [aviso] API CNES instável (tentativa {tentativa+1}/4): "
                      f"{type(e).__name__} — aguardando {espera}s ...")
                import time
                time.sleep(espera)
        if resp is None:
            print(f"  [aviso] API CNES fora do ar após 4 tentativas — seguindo com "
                  f"{len(registros_da_uf)} registro(s) já coletado(s) até aqui.")
            break
        data = resp.json()
        registros = data.get("estabelecimentos", data) if isinstance(data, dict) else data
        if not registros:
            break
        assinatura_atual = json.dumps(registros[0], sort_keys=True)
        if assinatura_atual == assinatura_anterior:
            break
        assinatura_anterior = assinatura_atual
        registros_da_uf.extend([r for r in registros if r.get("codigo_uf") == codigo_uf_alvo])
        offset_atual += len(registros)
        if len(registros_da_uf) >= meta_registros:
            break

    pdf = pd.json_normalize(registros_da_uf)
    if pdf.empty:
        # pd.json_normalize([]) não gera nenhuma coluna, e um parquet sem
        # colunas pode quebrar leituras futuras dessa fonte — mantém o
        # schema mínimo mesmo com 0 linhas, pra não deixar um arquivo
        # "quebrado" no bucket.
        pdf = pd.DataFrame(columns=["codigo_cnes", "nome_fantasia", "codigo_municipio",
                                     "bairro_estabelecimento", "estabelecimento_possui_atendimento_hospitalar",
                                     "estabelecimento_possui_centro_cirurgico",
                                     "latitude_estabelecimento_decimo_grau", "longitude_estabelecimento_decimo_grau"])
        print("  [aviso] 0 registros do CNES — subindo parquet vazio com schema mínimo.")
    out_path = f"{STAGING_DIR}/cnes_{UF}.parquet"
    pdf.to_parquet(out_path, index=False)
    print(f"[bronze/cnes] OK — {len(pdf)} estabelecimentos")
    upload_arquivo(client, out_path, f"bronze/cnes/cnes_{UF}.parquet")
    return len(pdf)


def bronze_leitos(client):
    caminho_utf8 = f"{STAGING_DIR}/leitos_{ANO}_utf8.csv"
    print(f"[bronze/leitos] baixando Leitos {ANO} (Latin-1 -> UTF-8) ...")
    resp = requests.get(LEITOS_URL, stream=True, timeout=120)
    resp.raise_for_status()
    with open(caminho_utf8, "w", encoding="utf-8", newline="") as f_out:
        for chunk in resp.iter_content(chunk_size=1024 * 1024):
            f_out.write(chunk.decode("latin-1"))

    comp_sql = ", ".join(str(ANO * 100 + m) for m in MESES)
    out_path = f"{STAGING_DIR}/leitos_{UF}_{ANO}.parquet"
    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT COMP, UF, MUNICIPIO, CNES, NOME_ESTABELECIMENTO,
                   LEITOS_EXISTENTES, LEITOS_SUS, UTI_TOTAL_EXIST, UTI_TOTAL_SUS
            FROM read_csv_auto('{caminho_utf8}')
            WHERE UF = '{UF}' AND COMP IN ({comp_sql})
        ) TO '{out_path}' (FORMAT PARQUET)
    """)
    total = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    con.close()
    print(f"[bronze/leitos] OK — {total} registros")
    upload_arquivo(client, out_path, f"bronze/leitos/leitos_{UF}_{ANO}.parquet")
    return total


if __name__ == "__main__":
    print("=" * 60)
    print("INGESTAO BRONZE — SUS+ Inteligente (Compute Instance + cron)")
    print("=" * 60)

    client = get_object_storage_client()
    falhas = []

    # SIH é a fonte crítica do projeto — se falhar, interrompe tudo (não
    # faz sentido seguir sem o dado principal).
    bronze_sih(client)

    # CNES e Leitos rodam de forma independente entre si e do SIH: uma
    # instabilidade temporária numa dessas fontes não deve impedir a outra
    # de atualizar, nem fazer a ingestão do dia inteira "sumir" do cron.
    try:
        bronze_cnes(client)
    except Exception as e:
        print(f"[ERRO] bronze_cnes falhou, mas seguindo (CNES não é crítico): {e}")
        falhas.append("cnes")

    try:
        bronze_leitos(client)
    except Exception as e:
        print(f"[ERRO] bronze_leitos falhou: {e}")
        falhas.append("leitos")

    if falhas:
        print(f"\nIngestão bronze concluída COM RESSALVAS — falharam: {falhas}")
        print("(SIH, a fonte principal, foi atualizado com sucesso)")
    else:
        print("\nIngestão bronze concluída com sucesso — todas as fontes atualizadas.")
