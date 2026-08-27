-- SUS+ Inteligente — External Tables novas (população + indicador extendido)
-- Rodar no SQL Worksheet do Oracle ADB (sus-inteligente-adb)
-- Pré-requisito: os arquivos já estão no Object Storage (feito por Renata):
--   sus-inteligente-input/auxiliares/populacao_municipios_sp_2024.csv
--   sus-inteligente-output/gold_csv/indicador_capacidade_municipio_extendido/*.csv

-- 1) Tabela de população (IBGE 2024, por município SP)
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

-- 2) Indicador de capacidade extendido (+ motivo dominante por município)
BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name     => 'INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO',
    credential_name => 'OBJ_STORAGE_CRED_RENATA',
    file_uri_list  => 'https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/grkdxjifyvni/b/sus-inteligente-output/o/gold_csv/indicador_capacidade_municipio_extendido/*.csv',
    format         => JSON_OBJECT('type' VALUE 'csv', 'skipheaders' VALUE '1'),
    column_list    => 'MUNICIPIO_CODIGO NUMBER, TOTAL_INTERNACOES NUMBER,
                        PERMANENCIA_MEDIA_DIAS NUMBER, ESTABELECIMENTOS_DISTINTOS NUMBER,
                        LEITOS_EXISTENTES_TOTAL NUMBER, LEITOS_SUS_TOTAL NUMBER,
                        INTERNACOES_POR_LEITO NUMBER, PROPORCAO_LEITOS_SUS NUMBER,
                        MOTIVO_DOMINANTE VARCHAR2(100), MOTIVO_DOMINANTE_SHARE NUMBER'
  );
END;
/

-- 3) Testar as duas — confirma que os dados vieram certos antes de considerar concluído
SELECT * FROM POPULACAO_MUNICIPIO WHERE ROWNUM <= 5;
SELECT * FROM INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO WHERE ROWNUM <= 5;

-- 4) Bônus — já testa uma pergunta cruzando as duas fontes, bom exemplo pra
--    validar o Select AI depois: "quais municípios têm mais internações por
--    1.000 habitantes?" (indicador normalizado por população, não só por leito)
SELECT i.municipio_codigo, p.nome_municipio, i.total_internacoes, p.populacao_estimada,
       ROUND(i.total_internacoes / p.populacao_estimada * 1000, 2) AS internacoes_por_mil_hab
FROM INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO i
JOIN POPULACAO_MUNICIPIO p ON i.municipio_codigo = p.codigo_municipio
ORDER BY internacoes_por_mil_hab DESC
FETCH FIRST 10 ROWS ONLY;
