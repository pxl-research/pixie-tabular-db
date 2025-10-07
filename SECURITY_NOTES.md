## LLM-datahygiëne — hoog

- Gevaar: ruwe productkolommen verlaten het platform richting Azure OpenAI.
- Aanpak: kolonwaarden anonimiseren of samenvatten, sanitizer toevoegen vóór `describe_attributes`, opt-out per collectie/upload en eventueel overschakelen op self-hosted LLM.

## Forwarded headers — hoog

- Gevaar: `uvicorn` vertrouwt iedereen vanwege `--forwarded-allow-ips *`, waardoor IP-spoofing mogelijk is.
- Aanpak: whitelist alleen de reverse proxy of verwijder de forwarding-vlaggen wanneer geen proxy betrokken is.

## Database exposure — hoog

- Gevaar: Postgres/Adminer draaien lokaal met standaardpoorten en gedeelde dev-credentials.
- Aanpak: bind deze services aan localhost, gebruik unieke accounts per omgeving en beperk Adminer tot ontwikkelaars.

## Upload DoS — middel

- Gevaar: uploads worden onbegrensd ingelezen in geheugen; grote of kwaadaardige bestanden kunnen de API uitputten.
- Aanpak: implementeer bestandsgrootte- en rijenlimieten, stream parsing waar mogelijk en voeg antivirus/validatoren toe.

## Secret governance — middel

- Gevaar: alle gevoelige variabelen leven in globale env-files; rotatie/audit ontbreken en risico op lek via logging of dumps stijgt.
- Aanpak: centraliseer secrets in een manager (Vault/KeyVault), rol sleutels periodiek en log secret-gebruik.

## Audit & logging — laag

- Gevaar: security-gevoelige acties (auth failures, LLM calls, admin deletes) worden niet gestructureerd geaudit.
- Aanpak: voeg gestructureerde auditlogs toe met retentiebeleid en stuur kritieke events naar SIEM/monitoring.

## Dependency hygiëne — laag

- Gevaar: afhankelijk van snel evoluerende libs (`openai`, `fastapi`, `sqlalchemy`) zonder geautomatiseerde vuln-scans.
- Aanpak: integreer Dependabot/Renovate en draai periodieke `pip-audit`/`uv pip audit` in CI.
