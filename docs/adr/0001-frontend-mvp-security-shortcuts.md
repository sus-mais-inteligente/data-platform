# Front-end MVP connects as ADMIN, with no authentication

Status: accepted

The Streamlit front-end connects to Oracle as `ADMIN` (not a scoped `USR_FRONTEND` account) and is served publicly with no login gate. Both were deliberate schedule-driven trade-offs, not oversights: `USR_FRONTEND` had no grant on the `GENAI_PROFILE` Select AI profile at the time, and building auth was deprioritized against the challenge deadline. A reader inspecting `ui_common._load_oracle_secrets` or the deployment's lack of any auth check should not "fix" this without knowing it was chosen, not missed.

## Consequences

A public URL currently grants full `ADMIN` database access via the app's Oracle connection, bounded in practice only by what the UI itself exposes and by Select AI's `object_list` scoping. Before this app is used beyond the challenge submission, add either a `USR_FRONTEND` grant on `GENAI_PROFILE` (restoring least-privilege DB access) or an application-level auth gate — ideally both.
