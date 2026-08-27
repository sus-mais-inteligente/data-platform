# SUS+ Inteligente

**Painel Inteligente de Acesso Hospitalar e Perfil de Atendimento**
Enterprise Challenge FIAP x Oracle 2026 — Grupo 51 (Turma 1TSCO)

**Equipe:**
- Renata Cristina de Oliveira (RM 569564) — infraestrutura, pipelines, EDA/modelagem
- Guilherme Francisco (RM 569145) — Oracle Autonomous DB, JOIN de municípios, Select AI
- Rafael Canto Xavier (RM 572513) — dashboard (Streamlit)

---

## O desafio

Criar um painel inteligente de acesso hospitalar usando dados públicos do
SUS/DATASUS, ajudando secretarias de saúde a identificar regiões com
pressão assistencial, perfis de atendimento em expansão, e volume de
internações crescendo.

**Requisitos do edital:**
- 3 fontes de dados em formatos diferentes: estruturado/relacional (SIH),
  JSON via API (CNES), CSV como External Table (dado auxiliar — população)
- Diferencial: Select AI da Oracle (perguntas em linguagem natural → SQL)
- 4 blocos analíticos: exploração/sazonalidade, indicadores de capacidade,
  padrões/agrupamentos (clusterização), explicabilidade

---

## Arquitetura

```
Compute Instance (cron diário, 6h)
        │  bronze_ingestao_vm.py
        ▼
OCI Object Storage (bronze/)
        │
        ▼
OCI Data Flow — PySpark (pipeline_dataflow.py)
        │  silver/ → gold/ → gold_csv/
        ▼
Oracle Autonomous Database (External Tables)
        │
        ├──► Select AI (consultas em linguagem natural)
        └──► Dashboard Streamlit
```

**Por que essa arquitetura:** rodamos com os recursos gratuitos disponíveis
no OCI (2 Compute Instances + ~R$1.500 em créditos), e por ser um desafio
"SUS + Oracle", fez sentido concentrar tudo na plataforma Oracle Cloud.

**Decisões técnicas documentadas (transparência de processo):**
- **Databricks foi abandonado** em favor do OCI Data Flow nativo — mais
  alinhado com a stack Oracle do desafio, sem custo de licença adicional.
- **OCI Functions foi abandonado** para a ingestão bronze — arquitetura
  ARM da Function causava falha de compilação com `pyreaddbc` (dependência
  do `pysus`). Substituído por Compute Instance + cron, mais simples e
  sem esse problema.
- **Credencial da External Table precisa ser Auth Token**, não a senha
  normal de login OCI — usar a senha causa falha silenciosa (ORA-20401,
  0 linhas retornadas, sem erro claro).
- **Caminho do `file_uri_list` precisa ser exato** — qualquer prefixo a
  mais no caminho do bucket também causa retorno silencioso de 0 linhas.

---

## Estrutura do repositório

```
data-platform/
├── README.md
├── requirements.txt
├── bronze_ingestao_vm.py            # ingestão bronze de produção (Compute Instance/cron)
├── pipeline_dataflow.py             # silver -> gold de produção (OCI Data Flow/PySpark)
├── pipeline_completo.py             # bronze -> silver -> gold local (DuckDB/Colab), dev/teste/EDA
├── auxiliar_populacao.py            # dado auxiliar de população (IBGE), CSV para External Table
├── eda_modelagem.py                 # EDA + clusterização + regressão
├── sql_para_guilherme.sql           # DDL das External Tables (população + indicador extendido)
└── docs/
    └── eda/                         # gráficos gerados (PNG), 01 a 11
```

## Como rodar

Recomendado: Google Colab (ambiente já testado). Também funciona local com Python 3.10+.

```bash
git clone https://github.com/sus-mais-inteligente/data-platform.git
pip install -r requirements.txt
```
No Colab, cada comando vai numa célula separada, com `!` na frente. Depois
de instalar, reinicie o runtime (`Runtime → Restart runtime`) antes de
rodar o pipeline — pacotes novos só carregam depois do restart.

```bash
# 1) Pipeline completo (bronze -> silver -> gold), no Colab:
python pipeline_completo.py

# 2) Dado auxiliar de população (IBGE):
python auxiliar_populacao.py

# 3) EDA + modelagem (depende dos passos 1 e 2 já terem rodado):
python eda_modelagem.py
```

Todos os scripts detectam automaticamente se estão rodando no Google Colab
e montam o Drive (`MyDrive/SUS_Inteligente/data/`); rodando localmente,
usam uma pasta `data/` no diretório atual.

**Produção (OCI):** a ingestão bronze roda sozinha via cron na Compute
Instance; o Data Flow precisa ser disparado manualmente (ou agendado) via
Console OCI, apontando pro `pipeline_dataflow.py` no bucket de scripts.

---

## Fontes de dados

| Fonte | Tipo | O que traz | Cobertura |
|---|---|---|---|
| **SIH/SUS** (grupo RD) | Parquet via `pysus` | Internações: diagnóstico, permanência, valor, município, CNES | SP, 2024 — só 4 meses (Fev/Jun/Ago/Dez) disponíveis na fonte, testado exaustivamente 2x |
| **CNES** | JSON via API pública | Cadastro de estabelecimentos (amostra ~300, API instável) | SP |
| **Leitos SUS** | CSV | Capacidade instalada por estabelecimento/mês | SP, 2024, 12 meses (mais completo que o SIH) |
| **População (IBGE)** | XLS → CSV (auxiliar) | População estimada por município, 2024 | SP, 645 municípios |

### Limitações conhecidas das fontes

- **2025 indisponível:** o DATASUS ainda não publicou o grupo RD (internações)
  do SIH para nenhum mês de 2025 — testado exaustivamente, não é bug do
  pipeline.
- **2024 parcial:** apenas 4 dos 12 meses do grupo RD estão disponíveis na
  fonte usada pelo `pysus` (Fev/Jun/Ago/Dez) — confirmado em dois testes
  independentes, mesmo tentando os 12 meses explicitamente.
- **Grupo RD vs. SP:** ao pedir vários meses de uma vez, o `pysus` pode
  trazer outros grupos do SIH junto (ex.: grupo "SP" — Serviços
  Profissionais, schema totalmente diferente de "RD" — internações). Os
  pipelines filtram e descartam qualquer arquivo que não seja do grupo RD,
  com aviso explícito no log.
- **CNES API instável:** a API `apidadosabertos.saude.gov.br` apresenta
  timeouts com frequência. Todos os scripts de ingestão (local e produção)
  têm retry com backoff exponencial (4 tentativas: 1s/2s/4s/8s) e degradam
  graciosamente (schema vazio, mas válido) se a API continuar fora do ar —
  isso nunca derruba o restante do pipeline.
- **SIH não responde "quais atendimentos terminam em internação":** essa
  fonte só registra internações que já aconteceram, não atendimentos
  prévios (pronto-socorro/consulta) que poderiam ou não evoluir pra
  internação. Ver seção "Próximos passos".
- **Suprimentos/insumos hospitalares:** a proposta original (Sprint 1)
  previa direcionar o atendimento também de acordo com a disponibilidade
  de recursos/suprimentos (ex.: materiais, medicamentos) de cada unidade.
  Após pesquisa, não foram encontrados dados públicos e estruturados sobre
  suprimentos hospitalares no SUS com granularidade suficiente para esse
  uso — por isso, essa dimensão não foi incorporada ao MVP. Fica como
  evolução futura caso uma fonte confiável seja identificada.
- **"Internações por leito" é um proxy relativo** de pressão assistencial
  entre municípios/estabelecimentos, não uma taxa de ocupação real (que
  exigiria dado de fluxo de altas/entradas por dia, não disponível nas
  fontes usadas).

---

## Pipelines

| Script | Onde roda | O que faz |
|---|---|---|
| `bronze_ingestao_vm.py` | Compute Instance (cron, 6h diário) | Ingestão bronze de produção: SIH, CNES, Leitos → Object Storage |
| `pipeline_dataflow.py` | OCI Data Flow (PySpark) | Silver → Gold de produção: trata os dados, classifica motivo (CID-10), calcula indicadores, gera CSVs para as External Tables |
| `pipeline_completo.py` | Local / Google Colab (DuckDB) | Pipeline completo bronze→silver→gold para desenvolvimento, teste e EDA — mesma lógica do Data Flow, em SQL/DuckDB |
| `auxiliar_populacao.py` | Local / Colab | Baixa e limpa a estimativa de população do IBGE (2024), gera o CSV auxiliar exigido pelo edital |
| `eda_modelagem.py` | Local / Colab | Gera os 11 gráficos de EDA, roda os modelos (clusterização + regressão), exporta CSVs finais |
| `bronze_sia_teste()` (dentro de `pipeline_completo.py`) | Local / Colab | Exploratório — testa disponibilidade do SIA (atendimentos ambulatoriais). Não faz parte do pipeline oficial ainda. |

### Camadas (bronze → silver → gold)

- **Bronze:** dado bruto de cada fonte, como veio (SIH, CNES, Leitos)
- **Silver:** tipado, limpo, com chaves de junção prontas (`internacoes`,
  `capacidade_estabelecimento`, `crosswalk_cnes_municipio`) — inclui a
  classificação de **capítulo CID-10** (`capitulo_cid`), que agrupa os
  milhares de códigos de diagnóstico em ~22 categorias legíveis
- **Gold:** indicadores agregados, prontos pra consumo:

| Tabela gold | O que responde |
|---|---|
| `sazonalidade_mensal` | Existe sazonalidade no volume de internações? |
| `volume_por_municipio` | Volume e perfil de internação por município |
| `capacidade_por_municipio` | Leitos disponíveis por município |
| `indicador_capacidade_municipio` | Pressão assistencial (internações por leito) — ranking |
| `indicador_capacidade_municipio_extendido` | + proporção de leitos SUS, + motivo dominante e sua concentração |
| `motivos_internacao` | Quais os principais motivos de internação (capítulo CID-10) |
| `motivo_por_municipio` | Onde cada motivo se concentra |
| `motivo_por_mes` | Existe sazonalidade por motivo? |

### External Tables no Oracle ADB

| Tabela | Fonte | Status |
|---|---|---|
| `INDICADOR_CAPACIDADE_MUNICIPIO` | gold_csv | ✅ criada e testada |
| `INDICADOR_CAPACIDADE_MUNICIPIO_EXTENDIDO` | gold_csv | ✅ criada (motivo dominante + % leitos SUS) |
| `POPULACAO_MUNICIPIO` | auxiliar (IBGE) | ✅ criada — resolve o requisito de CSV auxiliar do edital |
| Nome de município (JOIN com IBGE) | `kelvins/municipios-brasileiros` | 🔲 responsabilidade do Guilherme — `SUBSTR(codigo_ibge,1,6)` pra bater com o código de 6 dígitos do DATASUS |

---

## EDA e modelagem (`eda_modelagem.py`)

11 gráficos, organizados pelas 4 perguntas centrais do time:

**Sazonalidade**
1. `01_sazonalidade.png` — internações por mês
8. `08_sazonalidade_por_motivo.png` — heatmap: sazonalidade por motivo (não só volume total)

**Indicadores de capacidade**
2. `02_ranking_municipios.png` — top 15 municípios em pressão assistencial
9. `09_permanencia_por_municipio.png` — top 15 municípios com internações mais longas
10. `10_internacoes_por_habitante.png` — ranking normalizado por população (complementa o ranking por leito)

**Motivo e permanência**
3. `03_distribuicao_permanencia.png` — quais motivos têm as internações mais longas
6. `06_motivos_internacao.png` — principais motivos (capítulo CID-10)
7. `07_concentracao_motivo.png` — onde o motivo #1 mais se concentra
11. `11_pressao_motivo_permanencia.png` — cruzamento: pressão × motivo dominante × permanência, por município

**Padrões/agrupamentos (clusterização)**
4. `04_clusterizacao.png` — por **estabelecimento** (não só município): pressão vs. capacidade, com clusters nomeados como candidatos a **enviar** ou **receber** pacientes (apoio à decisão de redistribuição)

**Explicabilidade**
5. `05_explicabilidade.png` — Random Forest prevendo **internações por leito** (pressão real, não volume bruto). Variáveis: permanência média, % de leitos SUS, concentração num motivo dominante, diversidade de estabelecimentos. Direção do efeito indicada por cor. **R² = 31%** (ver limitações).

### Por que as variáveis de "leitos" não entram na explicabilidade

A pressão assistencial é calculada dividindo internações por leitos — usar
"leitos" como variável explicativa da própria pressão seria circular. Por
isso o modelo de explicabilidade usa só variáveis que não fazem parte do
cálculo do alvo.

### Nome de município nos gráficos

O `eda_modelagem.py` já traz nome de município nos gráficos e CSVs,
via JOIN direto com a base pública do IBGE (`kelvins/municipios-brasileiros`,
`SUBSTR(codigo_ibge,1,6)` — mesma lógica que o Guilherme está aplicando no
lado do Oracle). Isso roda independente do JOIN do Guilherme estar pronto
ou não — se a coluna de nome já existir na base gold (depois que ele subir
o JOIN dele), o script usa ela direto; senão, resolve sozinho.

---

## Limitações e próximos passos

### Limitação: explicabilidade do modelo de pressão assistencial (R² = 31%)

O modelo de regressão explica ~31% da variação da pressão assistencial
entre municípios usando variáveis derivadas do próprio SIH (permanência
média, % de leitos SUS, concentração num motivo dominante, diversidade de
estabelecimentos). Essas variáveis são, em maior ou menor grau, subprodutos
da própria internação — não capturam a causa raiz de por que a demanda
existe.

Existe um indicador consolidado de saúde pública — **ICSAP (Internações
por Condições Sensíveis à Atenção Primária)** — que associa diretamente a
qualidade/cobertura do atendimento ambulatorial (SIA/SUS) ao volume de
internações evitáveis: quando a atenção básica é fraca numa região,
condições simples (hipertensão, diabetes descompensada) evoluem pra
internação. Isso sugere que features derivadas do SIA teriam poder
explicativo mais forte que as atuais, por estarem ligadas à causa, não à
consequência.

Essa integração não foi feita nesta sprint — priorizamos consolidar a base
SIH+CNES+Leitos exigida no escopo do desafio. Fica documentado como
extensão natural do modelo.

### Outras pendências / próximos passos

- Testar Select AI (Guilherme)
- Construir o dashboard Streamlit (Rafael)
- JOIN de nome de município na tabela Oracle (Guilherme — `kelvins/municipios-brasileiros`)
- Testar integração com o SIA (atendimentos ambulatoriais) — ver limitação acima
- Interface para o paciente via chatbot de triagem — fase seguinte, depois
  de consolidada a parte de gestão/stakeholders

### O que NÃO é (pra evitar prometer o que não existe)

- **Não é IA preditiva/forecasting.** O modelo de regressão é
  explicabilidade (o que se associa à pressão *no presente*), não previsão
  temporal (não estima "a pressão em outubro vai ser X"). Forecasting real
  exigiria vários anos de histórico consistente, que a fonte ainda não tem
  disponível (só 1 ano parcial de dado).
- **Não é motor rodando como serviço.** É um notebook que gera gráficos e
  modelos sob demanda, não um endpoint com previsão em tempo real.
