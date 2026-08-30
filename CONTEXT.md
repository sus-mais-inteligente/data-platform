# CONTEXT.md — SUS+ Inteligente

Glossary of domain terms for the SUS+ Inteligente project (Painel Inteligente de Acesso Hospitalar e Perfil de Atendimento). This file is a glossary only — no implementation details.

## Terms

**Internação** — A hospital admission recorded in SIH/SUS (grupo RD). The core unit of analysis; distinct from "atendimento" (see below).

**Atendimento** — A patient encounter (e.g. pronto-socorro, consulta) that may or may not evolve into an internação. Not currently tracked by any data source in this project — SIH only records internações that already happened, not prior encounters. Distinguishing these two is important: don't conflate "atendimento" with "internação" when discussing scope.

**Pressão assistencial** ("capacity pressure") — A proxy indicator of demand relative to installed capacity, calculated as internações por leito (internações ÷ leitos). It is a relative ranking between municípios/estabelecimentos, not a true occupancy rate (which would require daily admission/discharge flow data, unavailable in current sources).

**Motivo dominante** — The most frequent capítulo CID-10 (diagnosis chapter) among a município's internações, plus `motivo_dominante_share`, its share of that município's total. Used to characterize what's driving demand in a given place.

**Capítulo CID-10** — One of ~22 human-readable categories that diagnosis codes are grouped into (e.g. "XIX. Lesões e envenenamentos (causas externas)"). Used instead of raw CID-10 codes for readability.

**Leito** — A hospital bed. `leitos_existentes_total` is all installed beds; `leitos_sus_total` is the subset available to SUS patients specifically; `proporcao_leitos_sus` is that ratio.

**Perfil (de agrupamento)** — The label assigned to a município by the clustering analysis, ranked by mean pressão assistencial: "Alta pressão (candidato a enviar pacientes)" (highest), "Equilibrado" (middle), "Capacidade ociosa (pode receber pacientes)" (lowest). Frames clustering as decision support for patient redistribution, not just descriptive grouping — this framing is intentional, carried over from the original EDA analysis.

**Gestor de secretaria de saúde** — The primary intended user of the dashboard: municipal/state health-secretariat staff exploring hospital-access data to identify regions under pressure, expanding care profiles, and rising admission volumes. Not the patient — patient-facing tooling (e.g. a triage chatbot) is an explicitly later phase, out of scope for this project.

## Data availability notes (not glossary, but load-bearing context)

- Coverage is **São Paulo state, 2024, partial year** — only 4 of 12 months of internação data are available at the source (Fev/Jun/Ago/Dez). 2025 data does not exist yet at DATASUS.
- **`MUNICIPIOS_BRASILEIROS`** (in Oracle) covers all of Brazil, not just SP — the app must not assume every row is in scope; SP municípios are identified by the codes present in the indicador tables, not by filtering the lookup table itself.
