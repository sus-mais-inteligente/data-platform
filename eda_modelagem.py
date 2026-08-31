"""
EDA + Modelagem — SUS+ Inteligente

Gera os gráficos de EDA (sazonalidade, ranking, distribuição, correlação)
e os dois modelos analíticos combinados no plano: clusterização (padrões/
agrupamentos) + regressão (explicabilidade). Salva os PNGs prontos para
colar direto nos slides 9 e 10 do PPT.

Como rodar (Google Colab):
    !pip install -q duckdb pandas matplotlib scikit-learn
    python eda_modelagem.py

Lê os dados da mesma pasta do Google Drive onde o pipeline_completo_v3.py
gravou o silver/gold (monta o Drive automaticamente se ainda não estiver
montado nesta sessão).
"""

import os
import duckdb
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_error


def _definir_base_dir():
    try:
        from google.colab import drive
        drive.mount('/content/drive')
        base = '/content/drive/MyDrive/SUS_Inteligente/data'
        print(f"[drive] montado. Lendo dados de: {base}")
        return base
    except ImportError:
        print("[drive] google.colab não encontrado — rodando fora do Colab, "
              "usando pasta local ./data")
        return "data"


BASE_DIR = _definir_base_dir()
GOLD_DIR = f"{BASE_DIR}/gold"
SILVER_DIR = f"{BASE_DIR}/silver"
# Salva os gráficos dentro do Drive (irmão de data/), não numa pasta local
# do Colab — senão eles somem quando a sessão reinicia/desconecta.
OUT_DIR = f"{BASE_DIR}/../docs/eda"
os.makedirs(OUT_DIR, exist_ok=True)

con = duckdb.connect()
plt.rcParams["figure.dpi"] = 120


IBGE_MUNICIPIOS_URL = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"
_cache_ibge = None  # evita baixar de novo a cada gráfico


def _carregar_municipios_ibge():
    """
    Baixa (uma vez, com cache em memória) a base pública de municípios do
    IBGE usada pelo Guilherme na tabela Oracle (kelvins/municipios-brasileiros).
    Essa fonte usa código de 7 dígitos; o DATASUS usa 6 — por isso o JOIN
    abaixo usa SUBSTR(codigo_ibge, 1, 6), igual combinamos com ele.
    Se o download falhar (sem internet, GitHub fora do ar etc.), devolve
    None e quem chamar cai de volta pro código IBGE sem quebrar o script.
    """
    global _cache_ibge
    if _cache_ibge is not None:
        return _cache_ibge
    try:
        ibge = con.sql(f"""
            SELECT DISTINCT
                SUBSTR(CAST(codigo_ibge AS VARCHAR), 1, 6) AS municipio_codigo,
                nome AS nome_municipio
            FROM read_csv_auto('{IBGE_MUNICIPIOS_URL}')
        """).df()
        _cache_ibge = ibge
        print(f"  [ibge] base de municípios carregada ({len(ibge)} registros)")
        return ibge
    except Exception as e:
        print(f"  [aviso] não consegui baixar a base do IBGE ({type(e).__name__}) — "
              f"usando código IBGE como rótulo neste gráfico.")
        return None


def _adicionar_nome_municipio(df):
    """
    Enriquece o DataFrame inteiro com a coluna 'nome_municipio' (JOIN com a
    base pública do IBGE), não só o rótulo do gráfico — assim os CSVs
    exportados e as tabelas impressas também saem com nome, pra dar pra
    revisar o EDA de ponta a ponta antes de levar isso pro pipeline OCI.

    Se o df já tiver uma coluna de nome (algum dos candidatos), não mexe.
    Se não conseguir o JOIN (sem internet etc.), devolve o df original
    sem quebrar nada — quem for plotar cai pro código IBGE mesmo.
    """
    candidatos = ["nome_municipio", "municipio_nome", "nome", "municipio"]
    if any(col in df.columns for col in candidatos):
        return df
    if "municipio_codigo" not in df.columns:
        return df

    ibge = _carregar_municipios_ibge()
    if ibge is None:
        return df

    df_temp = df.copy()
    df_temp["municipio_codigo"] = df_temp["municipio_codigo"].astype(str)
    df_com_nome = df_temp.merge(ibge, on="municipio_codigo", how="left")
    # reordena pra deixar o nome logo depois do código, mais fácil de revisar
    cols = df_com_nome.columns.tolist()
    cols.remove("nome_municipio")
    idx_codigo = cols.index("municipio_codigo")
    cols.insert(idx_codigo + 1, "nome_municipio")
    return df_com_nome[cols]


def _rotulo_municipio(df):
    """
    Retorna o nome do município pra usar como rótulo nos gráficos.
    Ordem de prioridade:
      1) se a base gold já tiver uma coluna de nome pronta (ex: depois que
         o Guilherme subir o JOIN dele pro Oracle), usa ela direto;
      2) senão, faz o JOIN aqui mesmo com a base pública do IBGE;
      3) se nada der certo (sem internet etc.), cai pro código IBGE puro —
         o script nunca quebra por causa disso.
    """
    candidatos = ["nome_municipio", "municipio_nome", "nome", "municipio"]
    for col in candidatos:
        if col in df.columns:
            print(f"  [nome_municipio] usando coluna '{col}' já presente na base")
            return df[col].astype(str)

    ibge = _carregar_municipios_ibge()
    if ibge is not None and "municipio_codigo" in df.columns:
        df_temp = df.copy()
        df_temp["municipio_codigo"] = df_temp["municipio_codigo"].astype(str)
        df_com_nome = df_temp.merge(
            ibge, on="municipio_codigo", how="left"
        )
        if df_com_nome["nome_municipio"].notna().any():
            # mantém código como sufixo pra municípios sem match (raro, mas visível)
            return df_com_nome["nome_municipio"].fillna(df_com_nome["municipio_codigo"])

    print("  [nome_municipio] não foi possível resolver o nome — usando código IBGE")
    return df["municipio_codigo"].astype(str)


# 1) EDA — Sazonalidade

print("1) Gráfico de sazonalidade ...")
saz = con.sql(f"SELECT * FROM read_parquet('{GOLD_DIR}/sazonalidade_mensal.parquet') ORDER BY mes_competencia").df()

# normaliza o mês pra string de 2 dígitos ("2" -> "02"), independente de
# como veio da fonte — evita rótulo vazio no gráfico por descasamento de tipo/formato
saz["mes_competencia"] = saz["mes_competencia"].astype(str).str.zfill(2)
nomes_mes = {"02": "Fev", "06": "Jun", "08": "Ago", "12": "Dez",
             "01": "Jan", "03": "Mar", "04": "Abr", "05": "Mai",
             "07": "Jul", "09": "Set", "10": "Out", "11": "Nov"}
saz["mes_label"] = saz["mes_competencia"].map(nomes_mes)

fig, ax = plt.subplots(figsize=(7, 4))
ax.bar(saz["mes_label"], saz["total_internacoes"], color="#028090")
ax.set_title("Internações por mês — SP, 2024 (meses disponíveis)")
ax.set_ylabel("Total de internações")
for i, v in enumerate(saz["total_internacoes"]):
    ax.text(i, v + 2000, f"{v:,}".replace(",", "."), ha="center", fontsize=9)
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/01_sazonalidade.png")
plt.close()
print(f"  salvo em {OUT_DIR}/01_sazonalidade.png")
if len(saz) < 12:
    faltando = 12 - len(saz)
    print(f"  NOTA: {len(saz)} de 12 meses de 2024 disponíveis na fonte "
          f"({faltando} não vieram) — limitação da fonte do SIH, não do "
          f"pipeline. Mencionem no slide.\n")
else:
    print("  Os 12 meses de 2024 vieram disponíveis desta vez.\n")


# 2) EDA — Ranking (top 15 municípios por pressão assistencial)

print("2) Gráfico de ranking ...")
rank = con.sql(f"""
    SELECT *
    FROM read_parquet('{GOLD_DIR}/indicador_capacidade_municipio.parquet')
    WHERE internacoes_por_leito IS NOT NULL
    ORDER BY internacoes_por_leito DESC
    LIMIT 15
""").df()

rank = _adicionar_nome_municipio(rank)
rotulos = _rotulo_municipio(rank)

fig, ax = plt.subplots(figsize=(7, 5))
ax.barh(rotulos, rank["internacoes_por_leito"], color="#00A896")
ax.invert_yaxis()
ax.set_xlabel("Internações por leito (proxy de pressão assistencial)")
ax.set_title("Top 15 municípios — maior pressão assistencial")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/02_ranking_municipios.png")
plt.close()
print(f"  salvo em {OUT_DIR}/02_ranking_municipios.png\n")


# 3) Permanência hospitalar — por motivo e por município, não só o total
#    (a distribuição sozinha não dizia "onde" nem "por quê" a permanência
#    é mais longa; agora decompõe nas duas dimensões que respondem isso)

print("3) Permanência hospitalar — por motivo e por município ...")
percentis = con.sql(f"""
    SELECT
        MIN(dias_permanencia) AS minimo,
        APPROX_QUANTILE(dias_permanencia, 0.5)  AS mediana,
        APPROX_QUANTILE(dias_permanencia, 0.9)  AS p90,
        APPROX_QUANTILE(dias_permanencia, 0.99) AS p99,
        MAX(dias_permanencia) AS maximo,
        COUNT(*) FILTER (WHERE dias_permanencia > 90) AS internacoes_longa_permanencia
    FROM read_parquet('{SILVER_DIR}/internacoes.parquet')
""").df()
print(percentis.to_string(index=False))

# 3a) Permanência média por motivo — já vem pronta em motivos_internacao
#     (calculada no pipeline), só precisa ordenar e plotar
perm_motivo = con.sql(f"""
    SELECT capitulo_cid, permanencia_media_dias, total_internacoes
    FROM read_parquet('{GOLD_DIR}/motivos_internacao.parquet')
    ORDER BY permanencia_media_dias DESC
    LIMIT 10
""").df()

fig, ax = plt.subplots(figsize=(8, 5))
ax.barh(perm_motivo["capitulo_cid"], perm_motivo["permanencia_media_dias"], color="#D64545")
ax.invert_yaxis()
ax.set_xlabel("Permanência média (dias)")
ax.set_title("Quais motivos têm as internações mais longas")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/03_distribuicao_permanencia.png")
plt.close()
print(f"  salvo em {OUT_DIR}/03_distribuicao_permanencia.png")

# 3b) Permanência média por município — top 15 mais longos, com um piso
#     mínimo de volume pra não deixar município com 1-2 casos raros no topo
perm_municipio = con.sql(f"""
    SELECT municipio_codigo, permanencia_media_dias, total_internacoes
    FROM read_parquet('{GOLD_DIR}/indicador_capacidade_municipio.parquet')
    WHERE total_internacoes >= 30
    ORDER BY permanencia_media_dias DESC
    LIMIT 15
""").df()
perm_municipio = _adicionar_nome_municipio(perm_municipio)
rotulos_perm = _rotulo_municipio(perm_municipio)

fig, ax = plt.subplots(figsize=(7, 5))
ax.barh(rotulos_perm, perm_municipio["permanencia_media_dias"], color="#028090")
ax.invert_yaxis()
ax.set_xlabel("Permanência média (dias)")
ax.set_title("Top 15 municípios — internações mais longas\n(mínimo 30 internações no período)")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/09_permanencia_por_municipio.png")
plt.close()
print(f"  salvo em {OUT_DIR}/09_permanencia_por_municipio.png")
print(f"  Outliers de longa permanência (>90 dias): {int(percentis['internacoes_longa_permanencia'][0])} "
      f"internações no total — cruzando com o gráfico acima dá pra ver se isso é\n"
      f"  concentrado num motivo específico (ex: psiquiátrico/crônico) ou espalhado.\n")


# 4) EDA — Motivos de internação (capítulo CID-10)
#    Cobre 3 das 4 perguntas do time:
#      - quais os motivos da internação
#      - em que município cada motivo se concentra
#      - existe sazonalidade por motivo
#    A 4a pergunta ("quais atendimentos terminam em internação") NÃO dá pra
#    responder com o SIH: essa fonte só registra internações que já
#    aconteceram, não atendimentos prévios (pronto-socorro/consulta) que
#    poderiam ou não evoluir pra internação. Precisaria de outra fonte
#    (dados de urgência/emergência do SUS), fora do escopo atual.

print("4) Motivos de internação (capítulo CID-10) ...")

# 4a) Quais os motivos
motivos = con.sql(f"""
    SELECT * FROM read_parquet('{GOLD_DIR}/motivos_internacao.parquet')
    ORDER BY total_internacoes DESC
    LIMIT 10
""").df()

fig, ax = plt.subplots(figsize=(8, 5))
ax.barh(motivos["capitulo_cid"], motivos["total_internacoes"], color="#028090")
ax.invert_yaxis()
ax.set_xlabel("Total de internações")
ax.set_title("Principais motivos de internação (capítulo CID-10)")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/06_motivos_internacao.png")
plt.close()
print(f"  salvo em {OUT_DIR}/06_motivos_internacao.png")

# 4b) Onde o motivo #1 mais se concentra (top 8 municípios)
motivo_top = motivos["capitulo_cid"].iloc[0]
concentracao = con.sql(f"""
    SELECT municipio_codigo, total_internacoes
    FROM read_parquet('{GOLD_DIR}/motivo_por_municipio.parquet')
    WHERE capitulo_cid = '{motivo_top}'
    ORDER BY total_internacoes DESC
    LIMIT 8
""").df()
concentracao = _adicionar_nome_municipio(concentracao)
rotulos_conc = _rotulo_municipio(concentracao)

fig, ax = plt.subplots(figsize=(7, 4))
ax.barh(rotulos_conc, concentracao["total_internacoes"], color="#D64545")
ax.invert_yaxis()
ax.set_xlabel("Total de internações")
ax.set_title(f"Onde se concentra: {motivo_top}\n(top 8 municípios)")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/07_concentracao_motivo.png")
plt.close()
print(f"  salvo em {OUT_DIR}/07_concentracao_motivo.png\n")

# 4c) Sazonalidade por motivo — heatmap (todos os motivos relevantes, não só
#     top 4) + qual município concentra cada um dos principais, pra responder
#     "existe sazonalidade por motivo" E "onde" ao mesmo tempo.
saz_motivo = con.sql(f"""
    SELECT capitulo_cid, mes_competencia, total_internacoes
    FROM read_parquet('{GOLD_DIR}/motivo_por_mes.parquet')
    WHERE capitulo_cid IN ({",".join(f"'{m}'" for m in motivos["capitulo_cid"].head(10))})
""").df()
saz_motivo["mes_competencia"] = saz_motivo["mes_competencia"].astype(str).str.zfill(2)
saz_motivo["mes_label"] = saz_motivo["mes_competencia"].map(nomes_mes)
pivot = saz_motivo.pivot(index="capitulo_cid", columns="mes_label", values="total_internacoes")
ordem_meses = [nomes_mes[m] for m in saz["mes_competencia"]]  # mesma ordem cronológica do gráfico 1
pivot = pivot.reindex(columns=ordem_meses)
pivot = pivot.reindex(motivos["capitulo_cid"].head(10))  # ordenado por volume total, motivo mais comum no topo

fig, ax = plt.subplots(figsize=(8, 6))
im = ax.imshow(pivot.values, aspect="auto", cmap="YlOrRd")
ax.set_xticks(range(len(pivot.columns)))
ax.set_xticklabels(pivot.columns)
ax.set_yticks(range(len(pivot.index)))
ax.set_yticklabels(pivot.index, fontsize=8)
for i in range(pivot.shape[0]):
    for j in range(pivot.shape[1]):
        val = pivot.values[i, j]
        if not np.isnan(val):
            ax.text(j, i, f"{int(val):,}".replace(",", "."), ha="center", va="center", fontsize=7)
ax.set_title("Sazonalidade por motivo — todos os meses disponíveis\n(cor = volume de internações)")
fig.colorbar(im, ax=ax, label="Total de internações")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/08_sazonalidade_por_motivo.png")
plt.close()
print(f"  salvo em {OUT_DIR}/08_sazonalidade_por_motivo.png")

# "onde" cada um dos top 5 motivos mais concentra (complementa o heatmap)
print("  Onde cada motivo mais concentra (top 5 motivos, top 1 município cada):")
for motivo in motivos["capitulo_cid"].head(5):
    top1 = con.sql(f"""
        SELECT municipio_codigo, total_internacoes
        FROM read_parquet('{GOLD_DIR}/motivo_por_municipio.parquet')
        WHERE capitulo_cid = '{motivo}'
        ORDER BY total_internacoes DESC LIMIT 1
    """).df()
    if len(top1):
        nome = _rotulo_municipio(top1).iloc[0]
        print(f"    {motivo}: {nome} ({int(top1['total_internacoes'].iloc[0]):,} internações)".replace(",", "."))
print()



# 5) Clusterização — por ESTABELECIMENTO (não só município), pressão
#    assistencial vs. capacidade instalada, pensando em redistribuição de
#    pacientes: quem está sob alta pressão (candidato a enviar pacientes)
#    vs. quem tem capacidade ociosa (candidato a receber)

print("5) Clusterização por estabelecimento — pressão vs. capacidade ...")
cluster_estab = con.sql(f"""
    SELECT
        i.cnes,
        COUNT(*) AS total_internacoes,
        ROUND(AVG(i.dias_permanencia), 1) AS permanencia_media_dias,
        ANY_VALUE(c.nome_estabelecimento) AS nome_estabelecimento,
        ANY_VALUE(c.municipio_nome) AS municipio_nome,
        ANY_VALUE(c.leitos_existentes_media) AS leitos_existentes,
        ANY_VALUE(c.leitos_sus_media) AS leitos_sus,
        ROUND(COUNT(*) / NULLIF(ANY_VALUE(c.leitos_existentes_media), 0), 2) AS internacoes_por_leito
    FROM read_parquet('{SILVER_DIR}/internacoes.parquet') i
    JOIN read_parquet('{SILVER_DIR}/capacidade_estabelecimento.parquet') c ON i.cnes = c.cnes
    WHERE c.leitos_existentes_media > 0
    GROUP BY i.cnes
""").df()
cluster_estab = cluster_estab.dropna(subset=["internacoes_por_leito"]).copy()
print(f"  Base: {len(cluster_estab)} estabelecimentos com leito e internação identificados\n")

features_cluster = ["internacoes_por_leito", "leitos_existentes", "permanencia_media_dias"]
X = cluster_estab[features_cluster].fillna(0)
X_scaled = StandardScaler().fit_transform(X)

kmeans = KMeans(n_clusters=3, random_state=42, n_init=10)
cluster_estab["cluster"] = kmeans.fit_predict(X_scaled)

# nomeia os clusters pela pressão média — ação sugerida explícita, pra
# ficar claro que isso apoia decisão de redistribuição, não só descrição
ordem_clusters = cluster_estab.groupby("cluster")["internacoes_por_leito"].mean().sort_values(ascending=False).index
nomes_cluster = {
    ordem_clusters[0]: "Alta pressão (candidato a enviar pacientes)",
    ordem_clusters[1]: "Equilibrado",
    ordem_clusters[2]: "Capacidade ociosa (pode receber pacientes)",
}
cluster_estab["perfil"] = cluster_estab["cluster"].map(nomes_cluster)

print(cluster_estab.groupby("perfil")[features_cluster].mean().round(1))
print()
print(cluster_estab["perfil"].value_counts())

fig, ax = plt.subplots(figsize=(9, 7))
cores = {
    "Alta pressão (candidato a enviar pacientes)": "#D64545",
    "Equilibrado": "#028090",
    "Capacidade ociosa (pode receber pacientes)": "#02C39A",
}
for perfil, grupo in cluster_estab.groupby("perfil"):
    ax.scatter(grupo["leitos_existentes"], grupo["internacoes_por_leito"],
               label=perfil, color=cores[perfil], alpha=0.6, s=35)
ax.set_xlabel("Leitos existentes (capacidade instalada)")
ax.set_ylabel("Internações por leito (pressão assistencial)")
ax.set_title("Estabelecimentos: pressão vs. capacidade\n(apoio à decisão de redistribuição de pacientes)")
ax.legend(fontsize=8, loc="upper right")

# rotula só os casos mais extremos de cada ponta (senão, com centenas de
# estabelecimentos, rotular todo mundo vira ilegível) — são exatamente os
# candidatos mais fortes a enviar ou receber pacientes, então são os que
# mais importam pra decisão de redistribuição
top_alta_pressao = cluster_estab[cluster_estab["perfil"] == "Alta pressão (candidato a enviar pacientes)"] \
    .nlargest(5, "internacoes_por_leito")
top_ociosa = cluster_estab[cluster_estab["perfil"] == "Capacidade ociosa (pode receber pacientes)"] \
    .nsmallest(5, "internacoes_por_leito")
for _, row in pd.concat([top_alta_pressao, top_ociosa]).iterrows():
    rotulo = f"{row['municipio_nome']}"
    ax.annotate(rotulo, (row["leitos_existentes"], row["internacoes_por_leito"]),
                fontsize=6.5, alpha=0.85, xytext=(4, 4), textcoords="offset points")

plt.tight_layout()
plt.savefig(f"{OUT_DIR}/04_clusterizacao.png")
plt.close()
print(f"  salvo em {OUT_DIR}/04_clusterizacao.png")
print("  NOTA: 'gravidade' não está diretamente disponível no SIH de forma")
print("  estruturada — usamos permanência média como proxy aproximada (casos")
print("  mais graves tendem a ficar internados por mais tempo). Um indicador")
print("  de gravidade mais preciso exigiria outra fonte/classificação clínica.\n")

# tabela impressa complementar — os 8 estabelecimentos mais fortes de cada
# ponta, com nome do estabelecimento e do município (visão completa, sem
# depender só de ler posição no gráfico)
print("  Top 8 estabelecimentos — candidatos mais fortes a ENVIAR pacientes:")
top8_enviar = cluster_estab[cluster_estab["perfil"] == "Alta pressão (candidato a enviar pacientes)"] \
    .nlargest(8, "internacoes_por_leito")[["nome_estabelecimento", "municipio_nome", "internacoes_por_leito", "leitos_existentes"]]
print(top8_enviar.to_string(index=False))
print("\n  Top 8 estabelecimentos — candidatos mais fortes a RECEBER pacientes:")
top8_receber = cluster_estab[cluster_estab["perfil"] == "Capacidade ociosa (pode receber pacientes)"] \
    .nsmallest(8, "internacoes_por_leito")[["nome_estabelecimento", "municipio_nome", "internacoes_por_leito", "leitos_existentes"]]
print(top8_receber.to_string(index=False))
print()

cluster_estab.to_csv(f"{GOLD_DIR}/estabelecimentos_com_cluster.csv", index=False)
print(f"Base de estabelecimentos com cluster salva em {GOLD_DIR}/estabelecimentos_com_cluster.csv\n")


# 6) Base por município para a explicabilidade (join com motivo dominante)

df = con.sql(f"""
    WITH motivo_ranqueado AS (
        SELECT municipio_codigo, capitulo_cid,
               total_internacoes,
               ROW_NUMBER() OVER (PARTITION BY municipio_codigo ORDER BY total_internacoes DESC) AS rn,
               SUM(total_internacoes) OVER (PARTITION BY municipio_codigo) AS total_municipio
        FROM read_parquet('{GOLD_DIR}/motivo_por_municipio.parquet')
    ),
    motivo_dominante AS (
        SELECT municipio_codigo, capitulo_cid AS motivo_dominante,
               ROUND(total_internacoes / NULLIF(total_municipio, 0), 3) AS motivo_dominante_share
        FROM motivo_ranqueado WHERE rn = 1
    )
    SELECT i.*, md.motivo_dominante, md.motivo_dominante_share
    FROM read_parquet('{GOLD_DIR}/indicador_capacidade_municipio.parquet') i
    LEFT JOIN motivo_dominante md ON i.municipio_codigo = md.municipio_codigo
""").df()
df = df.dropna(subset=["leitos_existentes_total", "internacoes_por_leito"]).copy()
df["proporcao_leitos_sus"] = (df["leitos_sus_total"] / df["leitos_existentes_total"]).round(3)

# Internações por 1.000 habitantes — complementa "internações por leito":
# esse mede pressão sobre a CAPACIDADE INSTALADA, o outro mede pressão sobre
# a POPULAÇÃO real. Um município pode ter poucos leitos só porque é pequeno
# (sem estar "sob pressão" de verdade) — cruzar com população esclarece isso.
# Depende do auxiliar_populacao.py já ter rodado; se o CSV não existir ainda,
# a coluna fica ausente e o resto do script continua normal (não quebra).
caminho_populacao = f"{BASE_DIR}/auxiliares/populacao_municipios_sp_2024.csv"
if os.path.exists(caminho_populacao):
    pop = con.sql(f"SELECT codigo_municipio AS municipio_codigo, populacao_estimada FROM read_csv_auto('{caminho_populacao}')").df()
    df = df.merge(pop, on="municipio_codigo", how="left")
    df["internacoes_por_mil_habitantes"] = (
        df["total_internacoes"] / df["populacao_estimada"] * 1000
    ).round(2)
    print(f"  [populacao] indicador de internações por 1.000 habitantes calculado "
          f"({df['populacao_estimada'].notna().sum()} de {len(df)} municípios com match)")
else:
    print(f"  [populacao] CSV não encontrado em {caminho_populacao} — rode auxiliar_populacao.py")
    print("  primeiro se quiser o indicador de internações por 1.000 habitantes. Seguindo sem ele.")

df = _adicionar_nome_municipio(df)  # pra ficar com nome no CSV final, não só código
print(f"Base para explicabilidade: {len(df)} municípios com indicador completo\n")

# 10) Ranking por internações por 1.000 habitantes (só roda se o CSV de
#     população já tiver sido processado — ver bloco acima)
if "internacoes_por_mil_habitantes" in df.columns:
    print("10) Ranking por internações por 1.000 habitantes (normalizado por população) ...")
    rank_pop = (df.dropna(subset=["internacoes_por_mil_habitantes"])
                  .sort_values("internacoes_por_mil_habitantes", ascending=False)
                  .head(15))
    rotulos_pop = _rotulo_municipio(rank_pop)

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(rotulos_pop, rank_pop["internacoes_por_mil_habitantes"], color="#7B2CBF")
    ax.invert_yaxis()
    ax.set_xlabel("Internações por 1.000 habitantes")
    ax.set_title("Top 15 municípios — maior demanda em relação à população\n(complementa o ranking por leito)")
    plt.tight_layout()
    plt.savefig(f"{OUT_DIR}/10_internacoes_por_habitante.png")
    plt.close()
    print(f"  salvo em {OUT_DIR}/10_internacoes_por_habitante.png\n")


# 11) Pressão assistencial x motivo dominante x permanência — fecha o
#     ciclo: não só "quem está sob pressão", mas "por que motivo" e "por
#     quanto tempo" as internações duram nesses municípios
print("11) Pressão assistencial x motivo dominante x permanência (top municípios) ...")
top_pressao = (df.dropna(subset=["internacoes_por_leito", "motivo_dominante", "permanencia_media_dias"])
                 .sort_values("internacoes_por_leito", ascending=False)
                 .head(15))
rotulos_pressao = _rotulo_municipio(top_pressao)

fig, ax = plt.subplots(figsize=(10, 7))
barras = ax.barh(rotulos_pressao, top_pressao["internacoes_por_leito"], color="#D64545")
ax.invert_yaxis()
ax.set_xlabel("Internações por leito (pressão assistencial)")
ax.set_title("Top 15 municípios em pressão assistencial:\nmotivo dominante e permanência média")

# anota cada barra com o motivo dominante + a permanência média daquele
# município — assim cada linha do gráfico já conta a história completa.
# NOTA: capitulo_cid já vem limpo (sem numeral romano) direto da silver
# desde que ajustamos o pipeline — não corta mais nada aqui. Cortar por
# ". " era arriscado: nomes como "Doenças do sangue e sist. imunitário"
# têm um ". " no meio do texto, não só no prefixo, e cortariam errado.
for barra, (_, row) in zip(barras, top_pressao.iterrows()):
    motivo_texto = row["motivo_dominante"]
    texto = f"{motivo_texto} ({row['motivo_dominante_share']*100:.0f}%) · {row['permanencia_media_dias']:.0f}d de permanência"
    ax.text(barra.get_width() + top_pressao["internacoes_por_leito"].max() * 0.015,
            barra.get_y() + barra.get_height() / 2, texto,
            va="center", ha="left", fontsize=6.5)

ax.set_xlim(0, top_pressao["internacoes_por_leito"].max() * 1.9)  # espaço pro texto não cortar
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/11_pressao_motivo_permanencia.png")
plt.close()
print(f"  salvo em {OUT_DIR}/11_pressao_motivo_permanencia.png\n")

# tabela completa impressa (motivo por extenso, todos os números) pra quem
# quiser os detalhes exatos sem depender de ler texto pequeno no gráfico
print("  Detalhe completo (top 15 em pressão):")
detalhe = top_pressao[["municipio_codigo", "internacoes_por_leito", "motivo_dominante",
                        "motivo_dominante_share", "permanencia_media_dias"]].copy()
detalhe["municipio_codigo"] = rotulos_pressao.values
detalhe = detalhe.rename(columns={"municipio_codigo": "municipio"})
print(detalhe.to_string(index=False))
print()


# 7) Regressão + explicabilidade — o que mais explica a PRESSÃO
#    assistencial (internações por leito), não o volume bruto — volume
#    bruto correlaciona trivialmente com tamanho do município/capacidade,
#    o que não ajuda a decisão. Por isso também tiramos "leitos" das
#    variáveis de entrada: como leitos é o próprio denominador da métrica
#    alvo, usá-lo como variável explicativa seria circular.

print("7) Regressão (Random Forest) + explicabilidade — o que explica a pressão ...")
features_reg = ["permanencia_media_dias", "estabelecimentos_distintos",
                 "proporcao_leitos_sus", "motivo_dominante_share"]
X_reg = df[features_reg].fillna(0)
y_reg = df["internacoes_por_leito"]

X_train, X_test, y_train, y_test = train_test_split(X_reg, y_reg, test_size=0.2, random_state=42)
modelo = RandomForestRegressor(n_estimators=200, random_state=42, max_depth=6)
modelo.fit(X_train, y_train)
y_pred = modelo.predict(X_test)

print(f"  R² (teste): {r2_score(y_test, y_pred):.3f}")
print(f"  MAE (teste): {mean_absolute_error(y_test, y_pred):.2f} internações/leito\n")

importancias = pd.Series(modelo.feature_importances_, index=features_reg).sort_values(ascending=False)
print("Importância das variáveis (o que mais explica a pressão assistencial):")
print(importancias.round(3).to_string())

# Nomes legíveis pro gráfico — "motivo_dominante_share" sozinho não diz nada
# pra quem não programou o modelo; a versão em português explica o que a
# variável representa de verdade.
rotulos_legiveis = {
    "permanencia_media_dias": "Permanência média (dias)",
    "estabelecimentos_distintos": "Nº de estabelecimentos distintos\n(diversidade da rede local)",
    "proporcao_leitos_sus": "% dos leitos que são SUS\n(vs. particular/convênio)",
    "motivo_dominante_share": "Concentração num motivo principal\n(% das internações no motivo mais comum)",
}

# Importância sozinha só diz "o quanto pesa", não "pra que lado empurra".
# Calculamos a correlação de cada variável com o alvo pra saber a direção:
# positiva = quando a variável sobe, a pressão tende a subir também.
direcao = X_reg.corrwith(y_reg).reindex(importancias.index)
cores_direcao = ["#D64545" if d > 0 else "#028090" for d in direcao]

fig, ax = plt.subplots(figsize=(8, 5))
labels_plot = [rotulos_legiveis.get(f, f) for f in importancias.index]
barras = ax.barh(labels_plot, importancias.values, color=cores_direcao)
ax.invert_yaxis()
ax.set_title(f"O que mais explica a pressão assistencial de um município\n"
             f"(modelo explica {r2_score(y_test, y_pred)*100:.0f}% da variação nos dados de teste)")
ax.set_xlabel("Importância relativa")
# legenda de cor explicando a direção do efeito, já que a cor carrega
# informação (vermelho = aumenta pressão, verde = reduz)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color="#D64545", label="↑ aumenta a pressão"),
                    Patch(color="#028090", label="↓ reduz a pressão")],
          fontsize=8, loc="lower right")
plt.tight_layout()
plt.savefig(f"{OUT_DIR}/05_explicabilidade.png")
plt.close()
print(f"\n  salvo em {OUT_DIR}/05_explicabilidade.png")
print("  Direção do efeito (correlação com a pressão assistencial):")
for feat, corr in direcao.items():
    seta = "↑ aumenta" if corr > 0 else "↓ reduz"
    print(f"    {rotulos_legiveis.get(feat, feat).splitlines()[0]}: {seta} a pressão (corr. {corr:+.2f})")
print("  NOTA: 'leitos existentes/SUS' foram deixados de fora das variáveis")
print("  de entrada de propósito — como a pressão é calculada dividindo por")
print("  leito, usá-lo pra explicar a própria pressão seria circular.\n")

df.to_csv(f"{GOLD_DIR}/municipios_indicador_extendido.csv", index=False)
print(f"Base de municípios (com motivo dominante) salva em {GOLD_DIR}/municipios_indicador_extendido.csv")
print("Gráficos prontos em docs/eda/ — já podem colar nos slides 9 e 10.")
