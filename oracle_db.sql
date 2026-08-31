-- SUS+ Inteligente — SQL do Oracle ADB (External Tables, views, permissões)
-- Documentação viva de tudo que precisa rodar no SQL Worksheet do
-- Autonomous Database (INTELIGENTESUS) — criação/recriação de external
-- tables, correções de schema, permissões do usuário do dashboard
-- (USR_FRONTEND) e histórico de decisões (o que foi tentado e substituído).
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

-- ⚠️ 5) SUPERADO — NÃO FAZER. Deixado aqui só como histórico.
--    Essa era a primeira solução (view juntando na consulta), de quando
--    achávamos que precisaria de external table nova. DEPOIS decidimos
--    trazer nome_municipio direto pra dentro da camada GOLD (ver itens 7
--    e 10) — mais simples pro Rafael e pro Select AI, sem precisar saber
--    que existe uma view especial. NÃO criar essa view.
--
-- CREATE OR REPLACE VIEW INDICADOR_CAPACIDADE_MUNICIPIO_COM_NOME AS
-- SELECT i.*, p.nome_municipio
-- FROM INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO i
-- LEFT JOIN POPULACAO_MUNICIPIO p ON i.municipio_codigo = p.codigo_municipio;

-- LIMPEZA — se essa view já foi criada (era, no início), apagar agora que
-- a gold já resolve isso sozinha. DBMS_CLOUD.CREATE_EXTERNAL_TABLE não
-- afeta views, então ela não é removida automaticamente pelos DROP TABLE
-- dos itens seguintes — precisa apagar manualmente:
DROP VIEW INDICADOR_CAPACIDADE_MUNICIPIO_COM_NOME;

-- 6) Permissões pro usuário do Streamlit (USR_FRONTEND, criado pelo Rafael)
--    GRANT é por objeto no Oracle — não existe "libera tudo de uma vez".
--    Cobre aqui tudo que o dashboard provavelmente vai consultar:
GRANT SELECT ON INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO TO USR_FRONTEND;
GRANT SELECT ON INDICADOR_CAPACIDADE_MUNICIPIO TO USR_FRONTEND;
GRANT SELECT ON MOTIVOS_INTERNACAO TO USR_FRONTEND;
GRANT SELECT ON MOTIVO_POR_MUNICIPIO TO USR_FRONTEND;
GRANT SELECT ON MOTIVO_POR_MES TO USR_FRONTEND;
GRANT SELECT ON POPULACAO_MUNICIPIO TO USR_FRONTEND;

-- 7) Recriar INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO com as colunas novas
--    (nome/população/internações-por-habitante agora vêm direto do
--    pipeline_dataflow.py, não só via view) — RODAR DEPOIS de subir o
--    script novo pro bucket e rodar a Data Flow Application de novo.
DROP TABLE INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO;

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
                        MOTIVO_DOMINANTE VARCHAR2(100), MOTIVO_DOMINANTE_SHARE NUMBER,
                        NOME_MUNICIPIO VARCHAR2(100), POPULACAO_ESTIMADA NUMBER,
                        INTERNACOES_POR_MIL_HABITANTES NUMBER'
  );
END;
/

-- Depois de recriar, o GRANT precisa ser refeito também (DROP TABLE some
-- com os grants antigos):
GRANT SELECT ON INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO TO USR_FRONTEND;

-- 8) Bug reportado pelo Rafael: meses ordenando alfabético (por nome),
--    não cronológico ("Dezembro" aparecendo fora de ordem). Causa: as
--    tabelas de mês só tinham o número do mês, sem o ano — dependendo de
--    como o dashboard monta o rótulo/ordena, ordena errado. Adicionamos
--    ANO_COMPETENCIA e ANO_MES (chave numérica tipo 202402) nas duas
--    tabelas gold que têm mês. RODAR DEPOIS de subir o pipeline_dataflow.py
--    novo e rodar a Data Flow Application de novo.

-- 8a) MOTIVO_POR_MES — primeiro vê a definição atual (não sabemos as
--     colunas exatas usadas quando foi criada):
SELECT DBMS_METADATA.GET_DDL('TABLE', 'MOTIVO_POR_MES') FROM DUAL;

-- Depois de ver o resultado acima, recriar acrescentando ANO_COMPETENCIA
-- e ANO_MES ao column_list (ajustar tipos/nomes conforme o que apareceu):
DROP TABLE MOTIVO_POR_MES;

BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name     => 'MOTIVO_POR_MES',
    credential_name => 'OBJ_STORAGE_CRED_RENATA',
    file_uri_list  => 'https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/grkdxjifyvni/b/sus-inteligente-output/o/gold_csv/motivo_por_mes/*.csv',
    format         => JSON_OBJECT('type' VALUE 'csv', 'skipheaders' VALUE '1'),
    column_list    => 'CAPITULO_CID VARCHAR2(100), ANO_COMPETENCIA NUMBER,
                        MES_COMPETENCIA NUMBER, TOTAL_INTERNACOES NUMBER,
                        ANO_MES NUMBER'
  );
END;
/

GRANT SELECT ON MOTIVO_POR_MES TO USR_FRONTEND;

-- 8b) SAZONALIDADE_MENSAL — essa é NOVA (nunca tinha virado external
--     table antes, só existia como parquet):
BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name     => 'SAZONALIDADE_MENSAL',
    credential_name => 'OBJ_STORAGE_CRED_RENATA',
    file_uri_list  => 'https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/grkdxjifyvni/b/sus-inteligente-output/o/gold_csv/sazonalidade_mensal/*.csv',
    format         => JSON_OBJECT('type' VALUE 'csv', 'skipheaders' VALUE '1'),
    column_list    => 'ANO_COMPETENCIA NUMBER, MES_COMPETENCIA NUMBER,
                        TOTAL_INTERNACOES NUMBER, PERMANENCIA_MEDIA_DIAS NUMBER,
                        VALOR_MEDIO_AIH NUMBER, VALOR_TOTAL_PERIODO NUMBER,
                        ANO_MES NUMBER'
  );
END;
/

GRANT SELECT ON SAZONALIDADE_MENSAL TO USR_FRONTEND;

-- Testar as duas, já ordenando pela chave certa:
SELECT * FROM MOTIVO_POR_MES ORDER BY ano_mes FETCH FIRST 10 ROWS ONLY;
SELECT * FROM SAZONALIDADE_MENSAL ORDER BY ano_mes;

-- Avisar o Rafael: usar ORDER BY ano_mes (não o nome do mês) em qualquer
-- gráfico/tabela que precise da ordem cronológica certa.

-- 9) BUG ENCONTRADO: MOTIVOS_INTERNACAO estava com column_list errado —
--    nomes de coluna nas posições erradas (provavelmente copiado sem
--    querer do schema de MOTIVO_POR_MUNICIPIO). O que aparecia como
--    "municipio_codigo" era na verdade total_internacoes, e o que
--    aparecia como "total_internacoes" era permanencia_media_dias.
--    Schema certo (essa tabela NÃO tem município, só motivo agregado):
DROP TABLE MOTIVOS_INTERNACAO;

BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name     => 'MOTIVOS_INTERNACAO',
    credential_name => 'OBJ_STORAGE_CRED_RENATA',
    file_uri_list  => 'https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/grkdxjifyvni/b/sus-inteligente-output/o/gold_csv/motivos_internacao/*.csv',
    format         => JSON_OBJECT('type' VALUE 'csv', 'skipheaders' VALUE '1'),
    column_list    => 'CAPITULO_CID VARCHAR2(100), TOTAL_INTERNACOES NUMBER,
                        PERMANENCIA_MEDIA_DIAS NUMBER, VALOR_MEDIO_AIH NUMBER'
  );
END;
/

GRANT SELECT ON MOTIVOS_INTERNACAO TO USR_FRONTEND;

SELECT * FROM MOTIVOS_INTERNACAO ORDER BY total_internacoes DESC FETCH FIRST 5 ROWS ONLY;

-- IMPORTANTE: como achamos esse erro por acaso numa tabela, vale a pena
-- conferir a MOTIVO_POR_MUNICIPIO também (mesma família, pode ter o
-- mesmo tipo de erro). Schema esperado dela (confirmar com
-- DBMS_METADATA.GET_DDL antes de mexer): capitulo_cid, municipio_codigo,
-- total_internacoes — nessa ordem.

-- CONFIRMADO pelo Guilherme: MOTIVO_POR_MUNICIPIO tinha o mesmo erro.
-- Correção:
DROP TABLE MOTIVO_POR_MUNICIPIO;

BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name     => 'MOTIVO_POR_MUNICIPIO',
    credential_name => 'OBJ_STORAGE_CRED_RENATA',
    file_uri_list  => 'https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/grkdxjifyvni/b/sus-inteligente-output/o/gold_csv/motivo_por_municipio/*.csv',
    format         => JSON_OBJECT('type' VALUE 'csv', 'skipheaders' VALUE '1'),
    column_list    => 'CAPITULO_CID VARCHAR2(100), MUNICIPIO_CODIGO NUMBER,
                        TOTAL_INTERNACOES NUMBER'
  );
END;
/

GRANT SELECT ON MOTIVO_POR_MUNICIPIO TO USR_FRONTEND;

-- testar: município aqui precisa ser código de 6 dígitos (tipo 355030),
-- não um número pequeno tipo total de internações
SELECT * FROM MOTIVO_POR_MUNICIPIO ORDER BY total_internacoes DESC FETCH FIRST 5 ROWS ONLY;

-- Depois de corrigir essas duas, vale conferir TODAS as external tables
-- que restaram (INDICADOR_CAPACIDADE_MUNICIPIO original, POPULACAO_MUNICIPIO)
-- com um SELECT rápido cada uma, só pra garantir que não tem mais nenhuma
-- com esse mesmo problema de coluna trocada.

-- 10) Adicionado nome_municipio na MOTIVO_POR_MUNICIPIO também (pedido
--     depois da correção do item 9) — RODAR DEPOIS de subir o
--     pipeline_dataflow.py novo e rodar a Data Flow de novo (senão o CSV
--     ainda não vai ter a coluna nova).
DROP TABLE MOTIVO_POR_MUNICIPIO;

BEGIN
  DBMS_CLOUD.CREATE_EXTERNAL_TABLE(
    table_name     => 'MOTIVO_POR_MUNICIPIO',
    credential_name => 'OBJ_STORAGE_CRED_RENATA',
    file_uri_list  => 'https://objectstorage.sa-saopaulo-1.oraclecloud.com/n/grkdxjifyvni/b/sus-inteligente-output/o/gold_csv/motivo_por_municipio/*.csv',
    format         => JSON_OBJECT('type' VALUE 'csv', 'skipheaders' VALUE '1'),
    column_list    => 'CAPITULO_CID VARCHAR2(100), MUNICIPIO_CODIGO NUMBER,
                        TOTAL_INTERNACOES NUMBER, NOME_MUNICIPIO VARCHAR2(100)'
  );
END;
/

GRANT SELECT ON MOTIVO_POR_MUNICIPIO TO USR_FRONTEND;

SELECT * FROM MOTIVO_POR_MUNICIPIO ORDER BY total_internacoes DESC FETCH FIRST 5 ROWS ONLY;
