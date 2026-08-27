"""
Dado auxiliar — População estimada por município (IBGE 2024)

Resolve o requisito do edital: "CSV como External Table — dado auxiliar
(população, região de saúde)". Usa a Estimativa de População do IBGE de
2024 (a mesma usada oficialmente pro TCU/FPM), filtrada pra SP — mesmo
recorte do resto do pipeline.

Fonte oficial (Diário Oficial da União, referência 01/07/2024):
    https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.xls

Como rodar (Google Colab):
    !pip install -q pandas xlrd duckdb
    python auxiliar_populacao.py

Saída:
    data/auxiliares/populacao_municipios_sp_2024.csv
    (mesma pasta base do pipeline_completo.py — sobe pro Drive automaticamente
    se estiver rodando no Colab)

Depois de gerado, o CSV precisa ser subido manualmente pro bucket
Object Storage (igual foi feito com indicador_capacidade_municipio), e
então criar a External Table no Oracle — SQL de exemplo no final deste
arquivo, nos comentários.
"""

import os
import re
import pandas as pd

UF_ALVO = "SP"
IBGE_URL = "https://ftp.ibge.gov.br/Estimativas_de_Populacao/Estimativas_2024/estimativa_dou_2024.xls"
# O arquivo tem 2 abas: "BRASIL E UFs" (agregado, não serve) e "MUNICÍPIOS"
# (o que precisamos, um registro por município).
IBGE_ABA = "MUNICÍPIOS"


def _definir_base_dir():
    try:
        from google.colab import drive
        drive.mount('/content/drive')
        base = '/content/drive/MyDrive/SUS_Inteligente/data'
        print(f"[drive] montado. Salvando em: {base}")
        return base
    except ImportError:
        print("[drive] google.colab não encontrado — usando pasta local ./data")
        return "data"


BASE_DIR = _definir_base_dir()
OUT_DIR = f"{BASE_DIR}/auxiliares"
os.makedirs(OUT_DIR, exist_ok=True)


def _encontrar_linha_cabecalho(df_bruto):
    """
    O .xls do IBGE vem com uma linha de título antes da tabela de verdade
    (nome do estudo, data etc.) — e essa linha de título também contém
    palavras como "MUNICÍPIOS" e "POPULAÇÃO" dentro da frase, o que dava
    falso positivo numa checagem simples. Por isso aqui exigimos que a
    linha tenha VÁRIAS células curtas (cabeçalhos de coluna de verdade,
    tipo "UF", "COD. MUNIC", "POPULAÇÃO ESTIMADA"), não uma única célula
    com uma frase longa.
    """
    palavras_chave = ["UF", "MUNIC", "POPULA", "NOME", "COD"]
    for i, row in df_bruto.iterrows():
        celulas = [str(v).strip().upper() for v in row.values if pd.notna(v)]
        if len(celulas) < 3:
            continue
        celulas_curtas = [c for c in celulas if len(c) <= 40]
        if len(celulas_curtas) < 3:
            continue  # linha de título costuma ter só 1 célula longa
        matches = sum(1 for c in celulas_curtas if any(p in c for p in palavras_chave))
        if matches >= 3:
            return i
    raise ValueError(
        "Não achei a linha de cabeçalho no .xls do IBGE — o layout do arquivo "
        "pode ter mudado. Abra o arquivo manualmente (link no topo deste script) "
        "e ajuste _encontrar_linha_cabecalho() ou os nomes de coluna abaixo."
    )


def gerar_populacao_municipios():
    print(f"[auxiliar/populacao] baixando estimativa IBGE 2024 ...")
    # header=None pra gente achar o cabeçalho real manualmente (linhas de
    # título variam entre publicações)
    bruto = pd.read_excel(IBGE_URL, sheet_name=IBGE_ABA, header=None, engine="xlrd")

    linha_cabecalho = _encontrar_linha_cabecalho(bruto)
    print(f"  cabeçalho real encontrado na linha {linha_cabecalho}")

    df = pd.read_excel(IBGE_URL, sheet_name=IBGE_ABA, header=linha_cabecalho, engine="xlrd")
    df.columns = [str(c).strip().upper() for c in df.columns]
    print(f"  colunas encontradas: {list(df.columns)}")

    # mapeia os nomes de coluna prováveis pra nomes padronizados —
    # o IBGE varia levemente a grafia entre publicações (ex: "COD. MUNIC"
    # vs "COD.\nMUNIC"), por isso o match é por substring, não igualdade exata
    def _achar_coluna(substrings):
        for col in df.columns:
            col_limpa = re.sub(r"\s+", " ", col)
            if any(s in col_limpa for s in substrings):
                return col
        return None

    col_uf = _achar_coluna(["UF"])
    col_cod_uf = _achar_coluna(["COD. UF", "COD.UF", "CÓD. UF"])
    col_cod_munic = _achar_coluna(["COD. MUNIC", "COD.MUNIC", "CÓD. MUNIC"])
    col_nome = _achar_coluna(["MUNICÍPIO", "MUNICIPIO", "NOME DO MUNIC"])
    col_pop = _achar_coluna(["POPULAÇÃO", "POPULACAO"])

    faltando = [n for n, c in [("UF", col_uf), ("cod_municipio", col_cod_munic),
                                ("nome", col_nome), ("populacao", col_pop)] if c is None]
    if faltando:
        raise ValueError(
            f"Não achei as colunas: {faltando}. Colunas disponíveis: {list(df.columns)}. "
            f"Ajuste os substrings de busca em _achar_coluna() pra essas colunas."
        )

    limpo = df[[col_uf, col_cod_uf, col_cod_munic, col_nome, col_pop]].copy()
    limpo.columns = ["uf", "codigo_uf", "codigo_municipio_ibge", "nome_municipio", "populacao_estimada"]

    # remove linhas de rodapé/nota (não tem UF de 2 letras)
    limpo = limpo[limpo["uf"].astype(str).str.len() == 2]
    limpo["codigo_uf"] = pd.to_numeric(limpo["codigo_uf"], errors="coerce")
    limpo["codigo_municipio_ibge"] = pd.to_numeric(limpo["codigo_municipio_ibge"], errors="coerce")
    limpo["populacao_estimada"] = pd.to_numeric(limpo["populacao_estimada"], errors="coerce")
    limpo = limpo.dropna(subset=["codigo_uf", "codigo_municipio_ibge", "populacao_estimada"])

    # IMPORTANTE: "COD. MUNIC" do IBGE vem SEM o prefixo da UF (ex: só "50308"
    # pra São Paulo, não "3550308"). Pra virar o código completo de 7 dígitos
    # (e depois o de 6 usado pelo DATASUS), precisa concatenar UF + município,
    # cada um com zero-padding — senão o JOIN com o SIH não casa nada.
    limpo["codigo_ibge_completo"] = (
        limpo["codigo_uf"].astype(int).astype(str).str.zfill(2)
        + limpo["codigo_municipio_ibge"].astype(int).astype(str).str.zfill(5)
    )
    # código de 6 dígitos, mesmo padrão usado no resto do pipeline pra casar
    # com municipio_codigo do SIH (SUBSTR igual ao JOIN do Guilherme com o IBGE)
    limpo["codigo_municipio"] = limpo["codigo_ibge_completo"].str[:6].astype(int)
    limpo["populacao_estimada"] = limpo["populacao_estimada"].astype(int)
    limpo = limpo[["uf", "codigo_municipio", "nome_municipio", "populacao_estimada"]]

    limpo_sp = limpo[limpo["uf"] == UF_ALVO].reset_index(drop=True)
    print(f"  total Brasil: {len(limpo)} municípios | filtrado {UF_ALVO}: {len(limpo_sp)} municípios")

    out_path = f"{OUT_DIR}/populacao_municipios_{UF_ALVO.lower()}_2024.csv"
    limpo_sp.to_csv(out_path, index=False)
    print(f"[auxiliar/populacao] OK — salvo em {out_path}")
    print("\nAmostra:")
    print(limpo_sp.head(5).to_string(index=False))
    return out_path


if __name__ == "__main__":
    gerar_populacao_municipios()
    print("\nPRÓXIMOS PASSOS (manuais, fora deste script):")
    print("  1. Subir o CSV gerado pro bucket, ex:")
    print("     sus-inteligente-input/auxiliares/populacao_municipios_sp_2024.csv")
    print("  2. Criar a External Table no Oracle ADB, algo como:")
    print("""
    BEGIN
      DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
        table_name     => 'POPULACAO_MUNICIPIO',
        credential_name => 'OBJ_STORAGE_CRED_RENATA',
        file_uri_list  => 'https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/grkdxjifyvni/b/sus-inteligente-input/o/auxiliares/populacao_municipios_sp_2024.csv',
        format         => JSON_OBJECT('type' VALUE 'csv', 'skipheaders' VALUE '1'),
        column_list    => 'UF VARCHAR2(2), CODIGO_MUNICIPIO NUMBER,
                            NOME_MUNICIPIO VARCHAR2(100), POPULACAO_ESTIMADA NUMBER'
      );
    END;
    /
    """)
    print("  3. Testar: SELECT * FROM POPULACAO_MUNICIPIO WHERE ROWNUM <= 5;")
    print("  4. (opcional, mais valor) cruzar com INDICADOR_CAPACIDADE_MUNICIPIO pra")
    print("     calcular internações por 1.000 habitantes — indicador ainda mais forte")
    print("     que só 'internações por leito', porque normaliza pelo tamanho real da")
    print("     população, não só pela capacidade instalada.")
