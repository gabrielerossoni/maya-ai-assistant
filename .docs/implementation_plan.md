# M.A.Y.A. — Piano di implementazione residuo

Questo documento contiene solo ciò che manca per trasformare l’assistente esistente in un agente dinamico e verificabile.

## Già presente — non da reimplementare

Routing LLM, ReAct limitato, tool manager, memoria ChromaDB/strutturata, automazioni persistenti, scheduler, proattività, permission engine, conferme Telegram, audit, dashboard FastAPI/WebSocket, voce, Telegram, MQTT/Home Assistant, plugin loader e test di base sono già presenti.

## Obiettivo

Implementare il ciclo persistente: `obiettivo → piano → azione → verifica → correzione → memoria → completamento`.

Una risposta del modello non conta come verifica: ogni completamento deve avere evidenza prodotta da un tool o da un controllo deterministico.

## 1. Modello persistente degli obiettivi

Creare `core/agency/models.py` e `core/agency/repository.py`.

Entità: `Goal` (id, titolo, descrizione, stato, priorità, scadenza, fonte, utente, contesto, piano), `Plan` (versione e stato), `PlanStep` (ordine, azione tool, dipendenze, tentativi, risultato, verifica, conferma) ed `ExecutionEvent` (tipo, payload, timestamp, correlation_id).

Stati: `draft`, `planned`, `running`, `waiting_input`, `waiting_confirmation`, `blocked`, `failed`, `completed`, `cancelled`.

Requisiti: SQLite separato dalla memoria conversazionale; aggiornamenti atomici; versionamento del piano; lock/claim dello step; idempotency key per side effect; recupero dei goal non terminali dopo riavvio; event log immutabile.

Test: crash durante step, doppio worker, retry dopo riavvio, ripresa senza duplicati.

## 2. Planner multi-step

Creare `core/agency/planner.py`. Deve distinguere risposta informativa, azione singola e obiettivo multi-step; usare solo tool registrati e parametri validi; esplicitare assunzioni e dati mancanti; produrre massimo 8 step configurabili; dichiarare dipendenze e criteri di successo; non eseguire side effect.

Schema minimo:

```json
{"goal":"...","assumptions":[],"steps":[{"id":"step-1","description":"...","tool":"calendar","action":{"action":"list"},"depends_on":[],"success_criteria":["..."]}]}
```

Il contesto deve includere richiesta, memoria rilevante, fatti/promemoria, goal attivi e disponibilità dei tool, con limite token e provenienza dei dati.

## 3. Approvazione e sicurezza

Prima dell’esecuzione mostrare risultato atteso, passi, side effect, dati mancanti e conferme. La conferma va associata a goal, versione piano, utente e scadenza; se il piano cambia, decade.

Estendere le policy a risorsa, side effect, utente, quantità, frequenza, orario e reversibilità. Ogni tool mutante deve dichiarare `supports_dry_run`, `supports_rollback`, effetto e risorse toccate. Implementare prima dry-run e rollback best-effort per calendario, memoria, MQTT/Home Assistant e automazioni.

## 4. Executor persistente

Creare `core/agency/orchestrator.py`.

Per ogni step: caricare goal e dipendenze; controllare precondizioni e permessi; verificare conferma e idempotency key; eseguire tramite `ToolManager`; salvare subito input/output; avviare il verificatore; decidere completamento, retry, correzione o blocco.

Deve funzionare da richiesta utente e come worker ripristinabile dallo scheduler.

## 5. Verifica, retry e correzione

Creare `core/agency/verifiers.py` con verificatori deterministici per:

- calendario: evento presente e campi coincidenti;
- memoria/note: record rileggibile dopo salvataggio;
- MQTT/Home Assistant: stato confermato entro timeout;
- reminder/timer: record persistito con orario corretto;
- ricerca/browser: risposta non vuota e fonte registrata;
- file/sistema: percorso, hash o stato atteso.

Formato: `{"status":"passed|failed|unknown","evidence":{},"reason":"..."}`. `unknown` non è successo.

Implementare massimo tentativi, backoff esponenziale, retry solo transient, nuova autorizzazione per retry sensibili, correzione del piano validata contro schema/permessi/tool, blocco con causa, timeout per step/goal, cancellazione cooperativa e cleanup.

## 6. Memoria degli obiettivi

Salvare a fine goal obiettivo, piano finale, prove, errori, decisioni e preferenze confermate. Aggiungere scope (`personal`, `home`, `work`, progetto) e filtrarlo prima della similarità semantica.

Creare un consolidatore che proponga fatti/preferenze con fonte, timestamp, confidence e conflitti. Le preferenze ad alto impatto richiedono conferma; il modello non può trasformare autonomamente un’ipotesi in preferenza.

## 7. Eventi esterni e dinamismo

Creare `core/events/` con adapter per calendario, MQTT/Home Assistant, Telegram, file osservati, notifiche locali ed email quando disponibile.

Envelope comune: tipo, fonte, timestamp, payload, deduplication key e permessi. Collegare agli obiettivi trigger separati da condizioni e azioni, con cooldown e deduplicazione. Implementare coda con priorità, deadline, concorrenza massima, lock sulle risorse, fairness e pausa per integrazione.

## 8. Osservabilità e valutazione

Propagare `correlation_id` da API/WebSocket/Telegram a tool e audit. Aggiungere vista dashboard `goal → step → azione → risultato → evidenza`.

Metriche: goal completati, completamenti senza intervento, verifiche fallite, falsi successi, retry, timeout, goal bloccati per causa, latenza planner/tool/verifier, token/costo per goal e side effect duplicati.

Creare `tests/agency/` con scenari per piano a tre step, retry, verifica fallita, tool assente, conferma rifiutata, riavvio, evento duplicato, conflitto tra goal, azione irreversibile e scadenza.

## Ordine di esecuzione

1. Modelli, repository, eventi, lock e idempotenza.
2. Planner strutturato e approvazione.
3. Executor e verificatori per calendario, memoria e MQTT/Home Assistant.
4. Retry, correzione, timeout e cancellazione.
5. Test scenario-based e metriche.
6. Memoria degli esiti e scope.
7. Ingestion eventi e trigger.
8. Dry-run, rollback e policy granulari.
9. Dashboard di esecuzione e hardening.

## Definition of done

Per almeno 10 scenari reali consecutivi Maya deve creare un piano quando serve, non eseguire side effect non autorizzati, persistere ogni step, verificare ogni risultato con evidenza, recuperare da errore o riavvio, ricordare l’esito, dichiarare i blocchi e produrre audit/metriche consultabili.

## Primo milestone

Completare i punti 1–5 per calendario, memoria strutturata e MQTT/Home Assistant. Test principale: creare un goal persistente, approvare il piano, eseguire azioni in ordine, verificare lo stato, ritentare un errore transient e restituire un riepilogo con prove.
