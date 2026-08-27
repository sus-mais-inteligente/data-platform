"""
SUS+ Inteligente — OCI Data Flow (PySpark)

Aplicação Spark para rodar como OCI Data Flow Application.
Lê os dados BRONZE (já baixados via pipeline_completo_v3.py / Colab e
enviados manualmente para o Object Storage) e faz o processamento
SILVER -> GOLD em Spark, gravando os resultados de volta no Object Storage.

Por que a ingestão (bronze) não está aqui:
    O Data Flow não tem acesso fácil a bibliotecas externas (pysus, requests)
    dentro do cluster Spark sem configurar um pacote de dependências à parte.
    Como o pipeline de ingestão já funciona (DuckDB/Colab), reaproveitamos
    esse resultado como entrada, e usamos o Data Flow para o processamento
    distribuído "de produção" — que é a parte que o Spark realmente resolve
    melhor que um script local.

ANTES DE RODAR — passos manuais:
    1. Rode pipeline_completo_v3.py normalmente (Colab) até gerar os
       arquivos em data/bronze/sih, data/bronze/cnes, data/bronze/leitos.
    2. Faça upload desses arquivos para um bucket de Object Storage, ex.:
           sus-inteligente-input/bronze/sih/sih_SP_2024.parquet
           sus-inteligente-input/bronze/cnes/cnes_SP.parquet
           sus-inteligente-input/bronze/leitos/leitos_SP_2024.parquet
       (pode ser feito pelo console da OCI: Object Storage > bucket > Upload)
    3. Ajuste NAMESPACE, INPUT_BUCKET e OUTPUT_BUCKET abaixo.
    4. Suba este script (.py) para um bucket também, ex. sus-inteligente-app/.
    5. Crie a OCI Data Flow Application apontando "File URL" para esse script.
       Spark version: 3.2 ou superior. Driver/Executor shape: VM.Standard.E4.Flex
       (menor configuração já é suficiente para este volume de dados).
    6. Rode a Application. Os resultados (gold) aparecem em OUTPUT_BUCKET,
       prontos para virar a external table no Oracle Autonomous Database.

Como rodar localmente para testar antes de subir (opcional):
    spark-submit pipeline_dataflow.py
    (nesse caso, os caminhos oci://... precisam de configuração de
    credenciais OCI no ambiente local — mais fácil testar direto na OCI)
"""

from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import IntegerType, DoubleType
from pyspark.sql.window import Window


# --- Configuração — ajuste antes de rodar -----------------------------
NAMESPACE = "grkdxjifyvni"
INPUT_BUCKET = "sus-inteligente-input"
OUTPUT_BUCKET = "sus-inteligente-output"

UF = "SP"
ANO = 2024

def oci_path(bucket, path):
    return f"oci://{bucket}@{NAMESPACE}/{path}"

BRONZE_SIH = oci_path(INPUT_BUCKET, f"bronze/sih/sih_{UF}_{ANO}.parquet")
BRONZE_CNES = oci_path(INPUT_BUCKET, f"bronze/cnes/cnes_{UF}.parquet")
BRONZE_LEITOS = oci_path(INPUT_BUCKET, f"bronze/leitos/leitos_{UF}_{ANO}.parquet")

SILVER_INTERNACOES = oci_path(OUTPUT_BUCKET, "silver/internacoes")
SILVER_CAPACIDADE = oci_path(OUTPUT_BUCKET, "silver/capacidade_estabelecimento")
SILVER_CROSSWALK = oci_path(OUTPUT_BUCKET, "silver/crosswalk_cnes_municipio")

GOLD_SAZONALIDADE = oci_path(OUTPUT_BUCKET, "gold/sazonalidade_mensal")
GOLD_VOLUME = oci_path(OUTPUT_BUCKET, "gold/volume_por_municipio")
GOLD_CAPACIDADE = oci_path(OUTPUT_BUCKET, "gold/capacidade_por_municipio")
GOLD_INDICADOR = oci_path(OUTPUT_BUCKET, "gold/indicador_capacidade_municipio")
GOLD_MOTIVOS = oci_path(OUTPUT_BUCKET, "gold/motivos_internacao")
GOLD_MOTIVO_MUNICIPIO = oci_path(OUTPUT_BUCKET, "gold/motivo_por_municipio")
GOLD_MOTIVO_MES = oci_path(OUTPUT_BUCKET, "gold/motivo_por_mes")
GOLD_INDICADOR_EXTENDIDO = oci_path(OUTPUT_BUCKET, "gold/indicador_capacidade_municipio_extendido")
# ------------------------------------------------------------------------


def classificar_capitulo_cid(col_diagnostico):
    """
    Agrupa o código CID-10 (ex: 'J189', 'I219') no capítulo correspondente
    (ex: 'Doenças do aparelho respiratório'), seguindo as 22 divisões
    oficiais da CID-10 (OMS/DATASUS). Sem isso, "motivo da internação"
    vira uma lista de milhares de códigos únicos e não ajuda ninguém a
    ler o gráfico.
    """
    letra = F.upper(F.substring(col_diagnostico, 1, 1))
    numero = F.substring(col_diagnostico, 2, 2).cast(IntegerType())

    return (F.when(letra.isin("A", "B"), "I. Doenças infecciosas e parasitárias")
        .when((letra == "C") | ((letra == "D") & (numero <= 48)), "II. Neoplasias (tumores)")
        .when((letra == "D") & (numero >= 50), "III. Doenças do sangue e sist. imunitário")
        .when(letra == "E", "IV. Doenças endócrinas, nutricionais e metabólicas")
        .when(letra == "F", "V. Transtornos mentais e comportamentais")
        .when(letra == "G", "VI. Doenças do sistema nervoso")
        .when((letra == "H") & (numero <= 59), "VII. Doenças do olho e anexos")
        .when((letra == "H") & (numero >= 60), "VIII. Doenças do ouvido")
        .when(letra == "I", "IX. Doenças do aparelho circulatório")
        .when(letra == "J", "X. Doenças do aparelho respiratório")
        .when(letra == "K", "XI. Doenças do aparelho digestivo")
        .when(letra == "L", "XII. Doenças da pele")
        .when(letra == "M", "XIII. Doenças osteomusculares")
        .when(letra == "N", "XIV. Doenças do aparelho geniturinário")
        .when(letra == "O", "XV. Gravidez, parto e puerpério")
        .when(letra == "P", "XVI. Afecções do período perinatal")
        .when(letra == "Q", "XVII. Malformações congênitas")
        .when(letra == "R", "XVIII. Sintomas e sinais anormais (sem diagnóstico fechado)")
        .when(letra.isin("S", "T"), "XIX. Lesões e envenenamentos (causas externas)")
        .when(letra.isin("V", "W", "X", "Y"), "XX. Causas externas de morbidade/mortalidade")
        .when(letra == "Z", "XXI. Contato com serviços de saúde (fatores diversos)")
        .when(letra == "U", "XXII. Códigos para propósitos especiais")
        .otherwise("Não classificado"))


def silver_transformar(spark):
    print("[silver] internações ...")
    sih = spark.read.parquet(BRONZE_SIH)
    internacoes = (sih
        .withColumn("cnes", F.col("CNES").cast(IntegerType()))
        .withColumn("municipio_residencia", F.col("MUNIC_RES").cast(IntegerType()))
        .withColumn("municipio_estabelecimento", F.col("MUNIC_MOV").cast(IntegerType()))
        .withColumn("data_internacao", F.to_date("DT_INTER", "yyyyMMdd"))
        .withColumn("data_saida", F.to_date("DT_SAIDA", "yyyyMMdd"))
        .withColumn("dias_permanencia", F.col("DIAS_PERM").cast(IntegerType()))
        .withColumn("valor_total", F.col("VAL_TOT").cast(DoubleType()))
        .withColumn("idade", F.col("IDADE").cast(IntegerType()))
        .withColumn("sexo", F.when(F.col("SEXO") == "1", "Masculino")
                              .when(F.col("SEXO") == "3", "Feminino")
                              .otherwise("Ignorado"))
        .withColumnRenamed("DIAG_PRINC", "diagnostico_principal")
        .withColumnRenamed("ANO_CMPT", "ano_competencia")
        .withColumnRenamed("MES_CMPT", "mes_competencia")
        .filter((F.col("dias_permanencia") >= 0) & (F.col("valor_total") >= 0))
        .withColumn("capitulo_cid", classificar_capitulo_cid(F.col("diagnostico_principal")))
        .select("cnes", "municipio_residencia", "municipio_estabelecimento",
                "data_internacao", "data_saida", "dias_permanencia", "valor_total",
                "idade", "sexo", "diagnostico_principal", "capitulo_cid",
                "ano_competencia", "mes_competencia"))
    internacoes.write.mode("overwrite").parquet(SILVER_INTERNACOES)

    print("[silver] capacidade por estabelecimento ...")
    leitos = spark.read.parquet(BRONZE_LEITOS)
    capacidade = (leitos
        .withColumn("cnes", F.col("CNES").cast(IntegerType()))
        .groupBy("cnes")
        .agg(F.first("NOME_ESTABELECIMENTO").alias("nome_estabelecimento"),
             F.first("MUNICIPIO").alias("municipio_nome"),
             F.round(F.avg("LEITOS_EXISTENTES")).alias("leitos_existentes_media"),
             F.round(F.avg("LEITOS_SUS")).alias("leitos_sus_media"),
             F.round(F.avg("UTI_TOTAL_EXIST")).alias("uti_existentes_media"),
             F.round(F.avg("UTI_TOTAL_SUS")).alias("uti_sus_media"),
             F.count("*").alias("meses_com_dado")))
    capacidade.write.mode("overwrite").parquet(SILVER_CAPACIDADE)

    print("[silver] crosswalk CNES -> município (derivado do SIH) ...")
    crosswalk = (internacoes
        .filter(F.col("cnes").isNotNull() & F.col("municipio_estabelecimento").isNotNull())
        .select("cnes", F.col("municipio_estabelecimento").alias("municipio_codigo"))
        .distinct())
    crosswalk.write.mode("overwrite").parquet(SILVER_CROSSWALK)

    print("[silver] concluído\n")
    return internacoes, capacidade, crosswalk


def gold_indicadores(spark, internacoes, capacidade, crosswalk):
    print("[gold] sazonalidade mensal ...")
    (internacoes.groupBy("mes_competencia")
        .agg(F.count("*").alias("total_internacoes"),
             F.round(F.avg("dias_permanencia"), 1).alias("permanencia_media_dias"),
             F.round(F.avg("valor_total"), 2).alias("valor_medio_aih"),
             F.sum("valor_total").alias("valor_total_periodo"))
        .orderBy("mes_competencia")
        .write.mode("overwrite").parquet(GOLD_SAZONALIDADE))

    print("[gold] volume por município ...")
    volume = (internacoes.filter(F.col("municipio_estabelecimento").isNotNull())
        .groupBy(F.col("municipio_estabelecimento").alias("municipio_codigo"))
        .agg(F.count("*").alias("total_internacoes"),
             F.round(F.avg("dias_permanencia"), 1).alias("permanencia_media_dias"),
             F.round(F.avg("idade"), 1).alias("idade_media"),
             F.round(F.avg("valor_total"), 2).alias("valor_medio_aih"),
             F.countDistinct("cnes").alias("estabelecimentos_distintos")))
    volume.write.mode("overwrite").parquet(GOLD_VOLUME)

    print("[gold] capacidade por município ...")
    cap_municipio = (capacidade.join(crosswalk, "cnes")
        .groupBy("municipio_codigo")
        .agg(F.sum("leitos_existentes_media").alias("leitos_existentes_total"),
             F.sum("leitos_sus_media").alias("leitos_sus_total"),
             F.sum("uti_existentes_media").alias("uti_existentes_total"),
             F.countDistinct("cnes").alias("estabelecimentos_com_leito")))
    cap_municipio.write.mode("overwrite").parquet(GOLD_CAPACIDADE)

    print("[gold] indicador de capacidade (ranking de pressão assistencial) ...")
    indicador = (volume.join(cap_municipio, "municipio_codigo", "left")
        .withColumn("internacoes_por_leito",
                    F.round(F.col("total_internacoes") / F.col("leitos_existentes_total"), 2))
        .withColumn("proporcao_leitos_sus",
                    F.round(F.col("leitos_sus_total") / F.col("leitos_existentes_total"), 3))
        .select("municipio_codigo", "total_internacoes", "permanencia_media_dias",
                "estabelecimentos_distintos", "leitos_existentes_total", "leitos_sus_total",
                "internacoes_por_leito", "proporcao_leitos_sus")
        .orderBy(F.col("internacoes_por_leito").desc_nulls_last()))
    indicador.write.mode("overwrite").parquet(GOLD_INDICADOR)
    # também grava uma versão CSV única, mais fácil de virar external table no Oracle
    indicador.coalesce(1).write.mode("overwrite").option("header", True).csv(
        oci_path(OUTPUT_BUCKET, "gold_csv/indicador_capacidade_municipio"))

    print("[gold] concluído\n")


def gold_motivos(spark, internacoes):
    print("[gold] motivos de internação (por capítulo CID-10) ...")

    print("  - motivos_internacao: 'quais os motivos da internação'")
    motivos = (internacoes.groupBy("capitulo_cid")
        .agg(F.count("*").alias("total_internacoes"),
             F.round(F.avg("dias_permanencia"), 1).alias("permanencia_media_dias"),
             F.round(F.avg("valor_total"), 2).alias("valor_medio_aih"))
        .orderBy(F.col("total_internacoes").desc()))
    motivos.write.mode("overwrite").parquet(GOLD_MOTIVOS)
    motivos.coalesce(1).write.mode("overwrite").option("header", True).csv(
        oci_path(OUTPUT_BUCKET, "gold_csv/motivos_internacao"))

    print("  - motivo_por_municipio: 'onde cada motivo se concentra'")
    motivo_municipio = (internacoes.filter(F.col("municipio_estabelecimento").isNotNull())
        .groupBy("capitulo_cid", F.col("municipio_estabelecimento").alias("municipio_codigo"))
        .agg(F.count("*").alias("total_internacoes"))
        .orderBy("capitulo_cid", F.col("total_internacoes").desc()))
    motivo_municipio.write.mode("overwrite").parquet(GOLD_MOTIVO_MUNICIPIO)
    motivo_municipio.coalesce(1).write.mode("overwrite").option("header", True).csv(
        oci_path(OUTPUT_BUCKET, "gold_csv/motivo_por_municipio"))

    print("  - motivo_por_mes: 'existe sazonalidade por motivo'")
    motivo_mes = (internacoes.groupBy("capitulo_cid", "mes_competencia")
        .agg(F.count("*").alias("total_internacoes"))
        .orderBy("capitulo_cid", "mes_competencia"))
    motivo_mes.write.mode("overwrite").parquet(GOLD_MOTIVO_MES)
    motivo_mes.coalesce(1).write.mode("overwrite").option("header", True).csv(
        oci_path(OUTPUT_BUCKET, "gold_csv/motivo_por_mes"))

    print("[gold] motivos concluído\n")
    print("  NOTA: a pergunta 'quais atendimentos terminam em internação' NÃO dá")
    print("  pra responder com o SIH — essa fonte só tem internações que já")
    print("  aconteceram, não atendimentos prévios (pronto-socorro/consulta).")
    print("  Precisaria de outra fonte (dados de urgência/emergência do SUS).\n")


def gold_indicador_extendido(spark):
    """
    Junta o indicador de capacidade (pressão assistencial) com o MOTIVO
    DOMINANTE de cada município — qual capítulo CID-10 concentra mais
    internações ali, e qual % isso representa do total do município.

    Mesma lógica de window function validada no eda_modelagem.py (Colab),
    só que em PySpark em vez de DuckDB, pra ficar disponível também no
    Oracle via external table (Select AI e dashboard podem consultar
    "por que município X está sob pressão" direto em SQL, sem precisar
    rodar Python).

    Roda separado de gold_indicadores()/gold_motivos() porque depende dos
    resultados das duas (lê de volta do Object Storage em vez de reusar
    os DataFrames em memória — mais simples de manter que passar tudo
    como parâmetro entre funções).
    """
    print("[gold] indicador extendido (+ motivo dominante) ...")
    indicador = spark.read.parquet(GOLD_INDICADOR)
    motivo_municipio = spark.read.parquet(GOLD_MOTIVO_MUNICIPIO)

    janela = Window.partitionBy("municipio_codigo").orderBy(F.col("total_internacoes").desc())
    motivo_dominante = (motivo_municipio
        .withColumn("total_municipio", F.sum("total_internacoes").over(
            Window.partitionBy("municipio_codigo")))
        .withColumn("rn", F.row_number().over(janela))
        .filter(F.col("rn") == 1)
        .select(F.col("municipio_codigo"),
                F.col("capitulo_cid").alias("motivo_dominante"),
                F.round(F.col("total_internacoes") / F.col("total_municipio"), 3).alias("motivo_dominante_share")))

    extendido = indicador.join(motivo_dominante, "municipio_codigo", "left")
    extendido.write.mode("overwrite").parquet(GOLD_INDICADOR_EXTENDIDO)
    extendido.coalesce(1).write.mode("overwrite").option("header", True).csv(
        oci_path(OUTPUT_BUCKET, "gold_csv/indicador_capacidade_municipio_extendido"))
    print(f"[gold] indicador extendido concluído — {extendido.count()} municípios\n")


if __name__ == "__main__":
    spark = SparkSession.builder.appName("sus_inteligente_silver_gold").getOrCreate()

    print("=" * 60)
    print("SUS+ Inteligente — OCI Data Flow (silver -> gold)")
    print("=" * 60)

    print("\n--- SILVER ---")
    internacoes, capacidade, crosswalk = silver_transformar(spark)

    print("--- GOLD ---")
    gold_indicadores(spark, internacoes, capacidade, crosswalk)
    gold_motivos(spark, internacoes)
    gold_indicador_extendido(spark)

    print(f"Concluído. Resultados gravados em: oci://{OUTPUT_BUCKET}@{NAMESPACE}/")
    spark.stop()
