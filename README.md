# Pixie Tabular DB

Pixie Tabular DB is een FastAPI-dienst met PostgreSQL voor het bewaren en raadplegen van tabelvormige productinformatie.

---

## Wat kun je ermee?

- Collections aanmaken als logische mappen voor productgegevens.
- CSV- of XLSX-bestanden uploaden; meerdere tabbladen worden automatisch gesplitst in losse documenten.
- Kolommen laten beschrijven en rangschikken via Azure OpenAI wanneer de bijhorende omgeving variabelen gevuld zijn.
- Rijen filteren op attribuutwaarden (exact of numeriek bereik) per document/product.

---

## Snel aan de slag

### Vereisten

- Python 3.12 en [uv](https://github.com/astral-sh/uv)
- Een PostgreSQL-instance (lokaal of via Docker)
- Optioneel: Azure OpenAI-gegevens voor LLM-verrijking

### Starten met Docker

```bash
cp .env.example .env.dev    # vul Postgres- en optioneel Azure-variabelen in
docker compose -f infra/docker/docker-compose.dev.yml up --build
```

De API draait daarna op http://localhost:8000, Postgres op poort 5432 en Adminer op 8080.
Stel het logniveau in via `LOG_LEVEL` in `.env.dev` (standaard `INFO`).

---

## Documenten beheren

1. **Authenticatie instellen** – voeg `PIXIE_API_KEY` toe aan je omgeving en gebruik dezelfde sleutel in de header `X-API-Key` bij elke collection/document-aanroep.
2. **Collectie maken** – `POST /collections/` met `{ "name": "producten" }`.
3. **Bestand uploaden** – `POST /collections/{naam}/documents/` met een multipart formulier:
   - veld `file`: CSV of XLSX;
   - optioneel `product_prefix`, `language`, `description`.
4. **Resultaat ophalen** – `GET /collections/{naam}/documents/` geeft per document de kolomnamen, het aantal rijen en eventuele LLM-beschrijvingen.
5. **Queries uitvoeren** – `POST /collections/{naam}/products/{product}/query` met filters zoals `{ "type": "exact", "name": "kleur", "value": "rood" }` of range-filters voor numerieke velden.

Wanneer Azure OpenAI-variabelen ontbreken, slaat de API enkel de ruwe schema- en rijgegevens op. De routes blijven bruikbaar, maar kolomomschrijvingen en rankings blijven leeg.

---

## Handige referenties

- `api/src/pixie_tabular_api/routers/documents.py` – stap-voor-stap verwerking van uploads.
- `db/init.sql` – schema van de PostgreSQL-tabellen.
- `infra/docker/docker-compose.dev.yml` – voorbeeldconfiguratie voor lokale ontwikkeling.
