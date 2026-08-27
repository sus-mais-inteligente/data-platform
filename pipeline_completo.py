"""
Pipeline completo — SUS+ Inteligente

Roda as 3 camadas em sequência. Cada camada também pode ser chamada
isoladamente (útil se só quiser re-rodar uma parte específica).

Como rodar (Google Colab):
    !pip install pysus requests pandas pyarrow duckdb scikit-learn
    python pipeline_completo.py

Este pipeline monta o Google Drive e salva bronze/silver/gold lá, para
que o trabalho de ingestão (a etapa mais lenta) não se perca se a
sessão do Colab reiniciar ou desconectar.

Estrutura de saída (dentro do Drive):
    MyDrive/SUS_Inteligente/data/bronze/   -> dados brutos, como vieram de cada fonte
    MyDrive/SUS_Inteligente/data/silver/   -> dados tratados, tipados, com chaves de junção prontas
    MyDrive/SUS_Inteligente/data/gold/     -> indicadores agregados, prontos para dashboard/modelo

Decisões e limitações conhecidas (documentadas ao longo do código):
    - SIH: só 4 dos 12 meses de 2024 disponíveis na fonte usada pelo
      pysus (fev, jun, ago, dez) — limitação da fonte, não do pipeline.
    - CNES (API): amostra de 300 estabelecimentos (paginação) — usado só
      como enriquecimento (nome/endereço), não como lista completa.
    - Leitos: cobertura completa de SP — fonte principal de capacidade.
    - UF_ZI (SIH) é código de MUNICÍPIO (6 dígitos), não de UF — usar
      os 2 primeiros dígitos para identificar a UF.
"""

import os
import json
import requests
import duckdb
import pandas as pd


UF = "SP"
ANO = 2024
# Testado exaustivamente antes: só Fev/Jun/Ago/Dez estavam disponíveis na
# fonte do pysus para 2024. Deixamos aqui tentando os 12 meses porque a
# fonte pode ter sido atualizada desde então — bronze_sih() já lida bem
# com meses que não vierem (avisa e segue com o que encontrar), então não
# quebra se voltar a ser só 4. Se vier tudo, ótimo: os gráficos de motivo/
# sazonalidade passam a cobrir o ano inteiro automaticamente.
MESES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]


# --- Google Drive (Colab) --------------------------------------------------
# Monta o Drive e usa uma pasta lá como base, em vez do disco efêmero do
# Colab. Se não estiver rodando no Colab (ex.: local), cai para uma pasta
# local "data/" normalmente, sem quebrar o script.

def _definir_base_dir():
    try:
        from google.colab import drive
        drive.mount('/content/drive')
        base = '/content/drive/MyDrive/SUS_Inteligente/data'
        print(f"[drive] montado. Salvando dados em: {base}")
        return base
    except ImportError:
        print("[drive] google.colab não encontrado — rodando fora do Colab, "
              "usando pasta local ./data")
        return "data"


BASE_DIR = _definir_base_dir()
BRONZE_DIR = f"{BASE_DIR}/bronze"
SILVER_DIR = f"{BASE_DIR}/silver"
GOLD_DIR = f"{BASE_DIR}/gold"
for d in [f"{BRONZE_DIR}/sih", f"{BRONZE_DIR}/cnes", f"{BRONZE_DIR}/leitos",
          f"{BRONZE_DIR}/auxiliares", SILVER_DIR, GOLD_DIR]:
    os.makedirs(d, exist_ok=True)

# Mapeamento oficial IBGE de UF -> código numérico
CODIGO_UF = {
    "RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17,
    "MA": 21, "PI": 22, "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27,
    "SE": 28, "BA": 29, "MG": 31, "ES": 32, "RJ": 33, "SP": 35, "PR": 41,
    "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53,
}

LEITOS_URL = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/Leitos_SUS/Leitos_2024.csv"

# Classificação do CID-10 (DIAG_PRINC) em capítulo, seguindo as 22 divisões
# oficiais da OMS/DATASUS. Sem isso, "motivo da internação" vira uma lista
# de milhares de códigos únicos e não ajuda ninguém a ler o gráfico.
# Usada tanto na camada silver (internações) quanto nos indicadores gold
# de motivo — mesma lógica replicada no pipeline_dataflow.py (PySpark),
# então os dois pipelines devem gerar os mesmos capítulos.
CASE_CAPITULO_CID = """
    CASE
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) IN ('A','B') THEN 'I. Doenças infecciosas e parasitárias'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'C'
             OR (UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'D' AND TRY_CAST(SUBSTR(DIAG_PRINC,2,2) AS INTEGER) <= 48)
             THEN 'II. Neoplasias (tumores)'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'D' AND TRY_CAST(SUBSTR(DIAG_PRINC,2,2) AS INTEGER) >= 50
             THEN 'III. Doenças do sangue e sist. imunitário'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'E' THEN 'IV. Doenças endócrinas, nutricionais e metabólicas'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'F' THEN 'V. Transtornos mentais e comportamentais'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'G' THEN 'VI. Doenças do sistema nervoso'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'H' AND TRY_CAST(SUBSTR(DIAG_PRINC,2,2) AS INTEGER) <= 59
             THEN 'VII. Doenças do olho e anexos'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'H' AND TRY_CAST(SUBSTR(DIAG_PRINC,2,2) AS INTEGER) >= 60
             THEN 'VIII. Doenças do ouvido'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'I' THEN 'IX. Doenças do aparelho circulatório'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'J' THEN 'X. Doenças do aparelho respiratório'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'K' THEN 'XI. Doenças do aparelho digestivo'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'L' THEN 'XII. Doenças da pele'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'M' THEN 'XIII. Doenças osteomusculares'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'N' THEN 'XIV. Doenças do aparelho geniturinário'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'O' THEN 'XV. Gravidez, parto e puerpério'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'P' THEN 'XVI. Afecções do período perinatal'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'Q' THEN 'XVII. Malformações congênitas'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'R' THEN 'XVIII. Sintomas e sinais anormais (sem diagnóstico fechado)'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) IN ('S','T') THEN 'XIX. Lesões e envenenamentos (causas externas)'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) IN ('V','W','X','Y') THEN 'XX. Causas externas de morbidade/mortalidade'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'Z' THEN 'XXI. Contato com serviços de saúde (fatores diversos)'
        WHEN UPPER(SUBSTR(DIAG_PRINC,1,1)) = 'U' THEN 'XXII. Códigos para propósitos especiais'
        ELSE 'Não classificado'
    END
"""



# CAMADA BRONZE — ingestão bruta de cada fonte

def bronze_sih():
    """SIH/SUS (grupo RD — internações), baixado com os meses configurados
    de uma vez e filtrado por UF/competência direto na consulta. A função
    sih() da versão atual do pysus já retorna a lista de paths dos
    parquets baixados, então usamos esse retorno direto (sem glob)."""
    from pysus import sih

    print(f"[bronze/sih] baixando {UF} {ANO} — meses {MESES} ...")
    arquivos_encontrados = sih(state=UF, year=ANO, month=MESES)
    arquivos_encontrados = [str(p) for p in arquivos_encontrados]

    # trava de segurança: pedir vários meses de uma vez pode trazer outros
    # grupos do SIH junto (ex: arquivos "SP...", schema totalmente diferente
    # de "RD..."). Descarta qualquer arquivo que não comece com "RD" no
    # nome — misturar schemas quebraria a leitura silenciosamente (colunas
    # viram NULL em vez de dar erro).
    descartados = [p for p in arquivos_encontrados if not os.path.basename(p).upper().startswith("RD")]
    if descartados:
        print(f"  [AVISO] {len(descartados)} arquivo(s) de outro grupo (não-RD) descartado(s):")
        for p in descartados:
            print(f"    IGNORADO: {p}")
    arquivos_encontrados = [p for p in arquivos_encontrados if os.path.basename(p).upper().startswith("RD")]

    if not arquivos_encontrados:
        raise FileNotFoundError("Nenhum mês do SIH (grupo RD) disponível para o recorte configurado.")

    print(f"  OK — {len(arquivos_encontrados)} arquivo(s) baixado(s):")
    for p in arquivos_encontrados:
        print(f"    {p}")
    if len(arquivos_encontrados) < len(MESES):
        faltando = len(MESES) - len(arquivos_encontrados)
        print(f"  [AVISO] {faltando} mês(es) do recorte configurado não vieram na resposta — "
              f"confira quais no filtro MES_CMPT abaixo, alguns podem não estar disponíveis na fonte.")

    colunas = ["UF_ZI", "ANO_CMPT", "MES_CMPT", "MUNIC_RES", "MUNIC_MOV",
               "DT_INTER", "DT_SAIDA", "DIAS_PERM", "VAL_TOT", "IDADE",
               "SEXO", "DIAG_PRINC", "CNES"]
    lista_arquivos_sql = ", ".join(f"'{p}'" for p in arquivos_encontrados)
    colunas_sql = ", ".join(colunas)
    out_path = f"{BRONZE_DIR}/sih/sih_{UF}_{ANO}.parquet"
    codigo_uf = str(CODIGO_UF[UF])
    meses_sql = ", ".join(f"'{m:02d}'" for m in MESES)

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
    print(f"[bronze/sih] OK — {total} registros salvos em {out_path}\n")


def bronze_cnes(meta_registros=300):
    """CNES via API pública — amostra (a API não pagina corretamente, então
    filtramos localmente pelo campo codigo_uf que vem em cada registro)."""
    url = "https://apidadosabertos.saude.gov.br/cnes/estabelecimentos"
    codigo_uf_alvo = CODIGO_UF[UF]
    registros_da_uf, total_varrido, offset_atual = [], 0, 0
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
                print(f"  [aviso] API CNES instável (tentativa {tentativa+1}/4): {type(e).__name__} "
                      f"— aguardando {espera}s e tentando de novo ...")
                import time
                time.sleep(espera)
        if resp is None:
            print(f"  [ERRO] API CNES fora do ar após 4 tentativas — abortando bronze_cnes com "
                  f"{len(registros_da_uf)} registro(s) já coletado(s). Rode bronze_cnes() de novo "
                  f"depois; as demais camadas (silver/gold) não dependem estritamente do CNES.")
            break
        data = resp.json()
        registros = data.get("estabelecimentos", data) if isinstance(data, dict) else data
        if not registros:
            break
        assinatura_atual = json.dumps(registros[0], sort_keys=True)
        if assinatura_atual == assinatura_anterior:
            break
        assinatura_anterior = assinatura_atual

        total_varrido += len(registros)
        registros_da_uf.extend([r for r in registros if r.get("codigo_uf") == codigo_uf_alvo])
        offset_atual += len(registros)
        if len(registros_da_uf) >= meta_registros:
            break

    out_json = f"{BRONZE_DIR}/cnes/cnes_{UF}_raw.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(registros_da_uf, f, ensure_ascii=False, indent=2)
    df = pd.json_normalize(registros_da_uf)
    if df.empty:
        # pd.json_normalize([]) não gera nenhuma coluna, e um parquet sem
        # colunas quebra a leitura no DuckDB depois (silver_transformar).
        # Cria as colunas mínimas que o silver espera, com 0 linhas, pra
        # o pipeline seguir rodando (o enriquecimento CNES fica vazio,
        # mas SIH/leitos/silver/gold continuam normalmente).
        colunas_minimas = ["codigo_cnes", "nome_fantasia", "codigo_municipio",
                            "bairro_estabelecimento", "estabelecimento_possui_atendimento_hospitalar",
                            "estabelecimento_possui_centro_cirurgico",
                            "latitude_estabelecimento_decimo_grau", "longitude_estabelecimento_decimo_grau"]
        df = pd.DataFrame(columns=colunas_minimas)
        print("  [aviso] 0 registros do CNES — salvando parquet vazio com schema mínimo "
              "(enriquecimento de estabelecimentos ficará sem dados desta fonte).")
    out_parquet = f"{BRONZE_DIR}/cnes/cnes_{UF}.parquet"
    df.to_parquet(out_parquet, index=False)
    print(f"[bronze/cnes] OK — {len(df)} estabelecimentos salvos em {out_parquet}\n")


def bronze_sia_teste():
    """
    EXPLORATÓRIO — testa se o SIA (Sistema de Informações Ambulatoriais,
    fonte de "atendimentos" que não viraram internação) está disponível
    pro recorte de vocês, e com quantos meses.

    Diferente de bronze_sih()/bronze_leitos(), essa função NÃO faz parte
    do pipeline oficial ainda — ela só baixa o grupo PA (Produção
    Ambulatorial, o principal do SIA) pra SP/2024, salva como veio (sem
    selecionar/renomear colunas, já que não sabemos o schema de cor) e
    imprime o que encontrou. A ideia é rodar isso, olhar o resultado
    junto, e só then desenhar o tratamento silver/gold pra essa fonte —
    igual foi feito com o SIH.

    Group codes do SIA (os mais comuns):
      PA  = Produção Ambulatorial (o principal, começamos por ele)
      BI  = Boletim de Produção Ambulatorial individualizado
      AM  = APAC de Medicamentos
      AQ  = APAC de Quimioterapia
      (lista completa: pysus.readthedocs.io/en/latest/databases/SIA.html)
    """
    from pysus import sia

    print(f"[bronze/sia] TESTE — baixando grupo PA, {UF} {ANO}, todos os meses ...")
    try:
        arquivos_encontrados = sia(state=UF, year=ANO, month=list(range(1, 13)), group="PA")
        arquivos_encontrados = [str(p) for p in arquivos_encontrados]
    except Exception as e:
        print(f"  [ERRO] SIA indisponível ou parâmetros incorretos: {type(e).__name__}: {e}")
        print("  Isso pode ser a fonte fora do ar, mudança na API do pysus, ou o grupo 'PA'")
        print("  não existir pro recorte — não é motivo pra travar o resto do pipeline.")
        return

    if not arquivos_encontrados:
        print("  [aviso] Nenhum mês do SIA/PA disponível para o recorte configurado.")
        return

    print(f"  OK — {len(arquivos_encontrados)} de 12 mês(es) disponível(is):")
    for p in arquivos_encontrados:
        print(f"    {p}")

    out_path = f"{BRONZE_DIR}/auxiliares/sia_pa_{UF}_{ANO}_teste.parquet"
    lista_arquivos_sql = ", ".join(f"'{p}'" for p in arquivos_encontrados)
    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT * FROM read_parquet([{lista_arquivos_sql}], union_by_name=True)
        ) TO '{out_path}' (FORMAT PARQUET)
    """)
    total = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out_path}')").fetchone()[0]
    colunas = con.sql(f"SELECT * FROM read_parquet('{out_path}') LIMIT 0").columns
    con.close()

    print(f"\n  [bronze/sia] TESTE OK — {total} registros salvos em {out_path}")
    print(f"  Colunas encontradas ({len(colunas)}): {colunas}")
    print("\n  PRÓXIMO PASSO: revisar essas colunas junto (principalmente se tem algo")
    print("  parecido com diagnóstico/CID, código de município, e CNES do")
    print("  estabelecimento) pra desenhar o tratamento silver/gold desta fonte.\n")


def bronze_leitos():
    """Dataset nacional de Leitos (Latin-1 -> UTF-8 em streaming, depois
    filtrado por UF/competência) — cobertura completa para a UF."""
    caminho_utf8 = f"{BRONZE_DIR}/leitos/_leitos_{ANO}_utf8_raw.csv"
    if not os.path.exists(caminho_utf8):
        print(f"[bronze/leitos] baixando Leitos {ANO} (Latin-1 -> UTF-8) ...")
        resp = requests.get(LEITOS_URL, stream=True, timeout=120)
        resp.raise_for_status()
        with open(caminho_utf8, "w", encoding="utf-8", newline="") as f_out:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f_out.write(chunk.decode("latin-1"))
    else:
        print(f"[bronze/leitos] usando cache: {caminho_utf8}")

    comp_sql = ", ".join(str(ANO * 100 + m) for m in MESES)
    out_path = f"{BRONZE_DIR}/leitos/leitos_{UF}_{ANO}.parquet"
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
    print(f"[bronze/leitos] OK — {total} registros salvos em {out_path}\n")



# CAMADA SILVER — limpeza de tipos e chaves de junção

def silver_transformar():
    con = duckdb.connect()

    print("[silver] internações ...")
    con.execute(f"""
        COPY (
            SELECT
                TRY_CAST(CNES AS INTEGER) AS cnes,
                TRY_CAST(MUNIC_RES AS INTEGER) AS municipio_residencia,
                TRY_CAST(MUNIC_MOV AS INTEGER) AS municipio_estabelecimento,
                TRY_CAST(strptime(DT_INTER, '%Y%m%d') AS DATE) AS data_internacao,
                TRY_CAST(strptime(DT_SAIDA, '%Y%m%d') AS DATE) AS data_saida,
                TRY_CAST(DIAS_PERM AS INTEGER) AS dias_permanencia,
                TRY_CAST(VAL_TOT AS DOUBLE) AS valor_total,
                TRY_CAST(IDADE AS INTEGER) AS idade,
                CASE SEXO WHEN '1' THEN 'Masculino' WHEN '3' THEN 'Feminino' ELSE 'Ignorado' END AS sexo,
                DIAG_PRINC AS diagnostico_principal,
                {CASE_CAPITULO_CID} AS capitulo_cid,
                ANO_CMPT AS ano_competencia,
                MES_CMPT AS mes_competencia
            FROM read_parquet('{BRONZE_DIR}/sih/sih_{UF}_{ANO}.parquet')
            WHERE TRY_CAST(DIAS_PERM AS INTEGER) >= 0 AND TRY_CAST(VAL_TOT AS DOUBLE) >= 0
        ) TO '{SILVER_DIR}/internacoes.parquet' (FORMAT PARQUET)
    """)

    print("[silver] capacidade por estabelecimento ...")
    con.execute(f"""
        COPY (
            SELECT
                TRY_CAST(CNES AS INTEGER) AS cnes,
                ANY_VALUE(NOME_ESTABELECIMENTO) AS nome_estabelecimento,
                ANY_VALUE(MUNICIPIO) AS municipio_nome,
                ROUND(AVG(LEITOS_EXISTENTES)) AS leitos_existentes_media,
                ROUND(AVG(LEITOS_SUS)) AS leitos_sus_media,
                ROUND(AVG(UTI_TOTAL_EXIST)) AS uti_existentes_media,
                ROUND(AVG(UTI_TOTAL_SUS)) AS uti_sus_media,
                COUNT(*) AS meses_com_dado
            FROM read_parquet('{BRONZE_DIR}/leitos/leitos_{UF}_{ANO}.parquet')
            GROUP BY TRY_CAST(CNES AS INTEGER)
        ) TO '{SILVER_DIR}/capacidade_estabelecimento.parquet' (FORMAT PARQUET)
    """)

    print("[silver] estabelecimentos enriquecidos (CNES/API) ...")
    con.execute(f"""
        COPY (
            SELECT
                codigo_cnes AS cnes, nome_fantasia, codigo_municipio AS municipio_codigo,
                bairro_estabelecimento AS bairro,
                estabelecimento_possui_atendimento_hospitalar AS possui_hospitalar,
                estabelecimento_possui_centro_cirurgico AS possui_centro_cirurgico,
                latitude_estabelecimento_decimo_grau AS latitude,
                longitude_estabelecimento_decimo_grau AS longitude
            FROM read_parquet('{BRONZE_DIR}/cnes/cnes_{UF}.parquet')
        ) TO '{SILVER_DIR}/estabelecimentos_enriquecido.parquet' (FORMAT PARQUET)
    """)

    print("[silver] crosswalk CNES -> município (derivado do SIH) ...")
    con.execute(f"""
        COPY (
            SELECT DISTINCT cnes, municipio_estabelecimento AS municipio_codigo
            FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
            WHERE cnes IS NOT NULL AND municipio_estabelecimento IS NOT NULL
        ) TO '{SILVER_DIR}/crosswalk_cnes_municipio.parquet' (FORMAT PARQUET)
    """)
    con.close()
    print("[silver] concluído\n")


# CAMADA GOLD — indicadores agregados

def gold_indicadores():
    con = duckdb.connect()

    print("[gold] sazonalidade mensal ...")
    con.execute(f"""
        COPY (
            SELECT mes_competencia, COUNT(*) AS total_internacoes,
                   ROUND(AVG(dias_permanencia), 1) AS permanencia_media_dias,
                   ROUND(AVG(valor_total), 2) AS valor_medio_aih,
                   SUM(valor_total) AS valor_total_periodo
            FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
            GROUP BY mes_competencia ORDER BY mes_competencia
        ) TO '{GOLD_DIR}/sazonalidade_mensal.parquet' (FORMAT PARQUET)
    """)

    print("[gold] volume por município ...")
    con.execute(f"""
        COPY (
            SELECT municipio_estabelecimento AS municipio_codigo,
                   COUNT(*) AS total_internacoes,
                   ROUND(AVG(dias_permanencia), 1) AS permanencia_media_dias,
                   ROUND(AVG(idade), 1) AS idade_media,
                   ROUND(AVG(valor_total), 2) AS valor_medio_aih,
                   COUNT(DISTINCT cnes) AS estabelecimentos_distintos
            FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
            WHERE municipio_estabelecimento IS NOT NULL
            GROUP BY municipio_estabelecimento
        ) TO '{GOLD_DIR}/volume_por_municipio.parquet' (FORMAT PARQUET)
    """)

    print("[gold] capacidade por município ...")
    con.execute(f"""
        COPY (
            SELECT cw.municipio_codigo,
                   SUM(cap.leitos_existentes_media) AS leitos_existentes_total,
                   SUM(cap.leitos_sus_media) AS leitos_sus_total,
                   SUM(cap.uti_existentes_media) AS uti_existentes_total,
                   COUNT(DISTINCT cap.cnes) AS estabelecimentos_com_leito
            FROM read_parquet('{SILVER_DIR}/capacidade_estabelecimento.parquet') cap
            JOIN read_parquet('{SILVER_DIR}/crosswalk_cnes_municipio.parquet') cw ON cap.cnes = cw.cnes
            GROUP BY cw.municipio_codigo
        ) TO '{GOLD_DIR}/capacidade_por_municipio.parquet' (FORMAT PARQUET)
    """)

    print("[gold] indicador de capacidade (ranking de pressão assistencial) ...")
    con.execute(f"""
        COPY (
            SELECT v.municipio_codigo, v.total_internacoes, v.permanencia_media_dias,
                   v.estabelecimentos_distintos, c.leitos_existentes_total, c.leitos_sus_total,
                   ROUND(v.total_internacoes / NULLIF(c.leitos_existentes_total, 0), 2) AS internacoes_por_leito
            FROM read_parquet('{GOLD_DIR}/volume_por_municipio.parquet') v
            LEFT JOIN read_parquet('{GOLD_DIR}/capacidade_por_municipio.parquet') c
              ON v.municipio_codigo = c.municipio_codigo
            ORDER BY internacoes_por_leito DESC NULLS LAST
        ) TO '{GOLD_DIR}/indicador_capacidade_municipio.parquet' (FORMAT PARQUET)
    """)
    con.close()
    print("[gold] concluído\n")


def gold_motivos():
    """
    Cobre 3 das 4 perguntas do time sobre motivos de internação:
      - quais os motivos ('motivos_internacao')
      - em que município cada motivo se concentra ('motivo_por_municipio')
      - existe sazonalidade por motivo ('motivo_por_mes')

    A 4a pergunta ("quais atendimentos terminam em internação") NÃO dá pra
    responder com o SIH: essa fonte só registra internações que já
    aconteceram, não atendimentos prévios (pronto-socorro/consulta) que
    poderiam ou não evoluir pra internação. Precisaria de outra fonte
    (dados de urgência/emergência do SUS), fora do escopo atual.
    """
    con = duckdb.connect()

    print("[gold] motivos de internação (capítulo CID-10) ...")
    con.execute(f"""
        COPY (
            SELECT capitulo_cid, COUNT(*) AS total_internacoes,
                   ROUND(AVG(dias_permanencia), 1) AS permanencia_media_dias,
                   ROUND(AVG(valor_total), 2) AS valor_medio_aih
            FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
            GROUP BY capitulo_cid ORDER BY total_internacoes DESC
        ) TO '{GOLD_DIR}/motivos_internacao.parquet' (FORMAT PARQUET)
    """)

    print("[gold] motivo por município ...")
    con.execute(f"""
        COPY (
            SELECT capitulo_cid, municipio_estabelecimento AS municipio_codigo,
                   COUNT(*) AS total_internacoes
            FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
            WHERE municipio_estabelecimento IS NOT NULL
            GROUP BY capitulo_cid, municipio_estabelecimento
            ORDER BY capitulo_cid, total_internacoes DESC
        ) TO '{GOLD_DIR}/motivo_por_municipio.parquet' (FORMAT PARQUET)
    """)

    print("[gold] motivo por mês (sazonalidade) ...")
    con.execute(f"""
        COPY (
            SELECT capitulo_cid, mes_competencia, COUNT(*) AS total_internacoes
            FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
            GROUP BY capitulo_cid, mes_competencia
            ORDER BY capitulo_cid, mes_competencia
        ) TO '{GOLD_DIR}/motivo_por_mes.parquet' (FORMAT PARQUET)
    """)
    con.close()
    print("[gold] motivos concluído\n")


# =================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("PIPELINE COMPLETO — SUS+ Inteligente (bronze -> silver -> gold)")
    print("=" * 60)

    print("\n--- BRONZE ---")
    bronze_sih()
    bronze_cnes()
    bronze_leitos()

    print("--- SILVER ---")
    silver_transformar()

    print("--- GOLD ---")
    gold_indicadores()
    gold_motivos()

    print("Pipeline completo. Rodem eda_modelagem.py em seguida para os")
    print("gráficos e modelos.")
