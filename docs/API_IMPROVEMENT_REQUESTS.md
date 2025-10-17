# API Verbetering Verzoeken voor Pixie Tabular API

**Datum:** 15 oktober 2025  
**Van:** Upload UI Team  
**Aan:** DB Team

---

## Samenvatting

Tijdens de ontwikkeling van de Upload UI zijn we enkele discrepanties en ontbrekende features tegengekomen in de API responses. Dit document beschrijft de gewenste aanpassingen om de UI beter te laten functioneren.

---

## 1. Collection Response: Voeg `document_count` toe

**Status:** ✅ Geïmplementeerd (17 oktober 2025)

### Huidige situatie
```json
GET /collections/
[
  {
    "id": 1,
    "name": "my-collection"
  }
]
```

### Gewenste situatie
```json
GET /collections/
[
  {
    "id": 1,
    "name": "my-collection",
    "document_count": 42
  }
]
```

### Waarom?
- De UI wil het aantal documenten per collectie tonen zonder voor elke collectie een extra API call te doen
- Betere gebruikerservaring: gebruikers zien direct hoeveel documenten in een collectie zitten
- Performance verbetering: anders moet de UI voor elke collectie `GET /collections/{name}/documents/` aanroepen

### Prioriteit
🔴 **Hoog** - Momenteel lossen we dit op met fallback naar 0, maar dit is niet ideaal

---

## 2. Document Response: Voeg metadata velden toe

**Status:** ✅ Geïmplementeerd (17 oktober 2025)

### Huidige situatie
Bij upload kunnen `language` en `description` worden meegegeven, maar deze komen niet terug in de Document response.

**Upload request:**
```
POST /collections/my-collection/documents/
Content-Type: multipart/form-data

file: products.csv
language: "NL"
description: "Q4 2025 productcatalogus"
```

**Response bevat deze velden NIET:**
```json
{
  "id": 123,
  "file_name": "products.csv",
  "collection": "my-collection",
  "product": "product-abc",
  "row_count": 1000,
  "columns": ["id", "name", "price"]
}
```

### Gewenste situatie
```json
{
  "id": 123,
  "file_name": "products.csv",
  "collection": "my-collection",
  "product": "product-abc",
  "row_count": 1000,
  "columns": ["id", "name", "price"],
  "language": "NL",
  "description": "Q4 2025 productcatalogus"
}
```

### Waarom?
- Gebruikers willen zien welke metadata bij een document hoort
- Consistentie: wat je upload moet je ook terug kunnen krijgen
- Documentbeheer: gebruikers kunnen zien welke taal/beschrijving bij data hoort
- Debugging: makkelijker om te zien of de juiste metadata is opgeslagen

### Prioriteit
🟡 **Medium** - Verbetert gebruikerservaring significant

---

## 3. Document List Response: Wrapper object verwijderen (of documenteren)

### Huidige situatie (onduidelijk)
De API spec suggereert dat `GET /collections/{name}/documents/` een array teruggeeft:

```json
[
  { "id": 1, "file_name": "doc1.csv", ... },
  { "id": 2, "file_name": "doc2.csv", ... }
]
```

Maar onze code verwacht een wrapper:
```json
{
  "documents": [
    { "id": 1, "file_name": "doc1.csv", ... },
    { "id": 2, "file_name": "doc2.csv", ... }
  ]
}
```

### Vraag
Wat geeft de API daadwerkelijk terug? En welke vorm is de bedoeling?

### Aanbeveling
- **Optie A (voorkeur):** Direct array terugeven - eenvoudiger en gebruikelijk
- **Optie B:** Wrapper object met paginering:
  ```json
  {
    "documents": [...],
    "total": 100,
    "limit": 50,
    "offset": 0
  }
  ```
  Dit is handig als je later paginering wilt toevoegen.

### Prioriteit
🟢 **Laag** - Werkaround is eenvoudig, maar consistentie is belangrijk

---

## 4. Upload Response: Return consistent Document object

### Huidige situatie
Upload geeft een **array** van Document objecten terug (omdat één Excel bestand meerdere sheets kan hebben):

```json
[
  {
    "id": 123,
    "file_name": "products.csv",
    "collection": "my-collection",
    "product": "product-abc",
    "row_count": 1000,
    "columns": ["id", "name", "price"]
  }
]
```

### Probleem
Onze UI gebruikt `identifier` (string) en verwacht een enkel object met status. Dit is inconsistent met de rest van de API.

### Gewenste situatie (keuze maken)

**Optie A:** Blijf array gebruiken (voorkeur):
```json
[
  {
    "id": 123,
    "file_name": "products.csv",
    "collection": "my-collection",
    "product": "product-abc",
    "row_count": 1000,
    "columns": ["id", "name", "price"],
    "status": "processing"
  }
]
```

**Optie B:** Enkel object met status:
```json
{
  "document": {
    "id": 123,
    "file_name": "products.csv",
    ...
  },
  "status": "processing",
  "message": "Document is being processed"
}
```

### Waarom?
- UI moet weten of upload succesvol was
- UI moet document kunnen highlighten na upload (heeft `id` nodig)
- Consistentie met andere endpoints

### Prioriteit
🟡 **Medium** - Werkaround is mogelijk maar niet ideaal

---

## 5. Toekomstige Feature: Bulk Operations (Nice to have)

### Niet dringend, maar handig voor later:

1. **Bulk delete documenten:**
   ```
   DELETE /collections/{name}/documents/
   Body: { "identifiers": [123, 456, 789] }
   ```

2. **Document metadata update:**
   ```
   PATCH /collections/{name}/documents/{id}
   Body: { "description": "Updated description", "language": "EN" }
   ```

3. **Collectie update:**
   ```
   PATCH /collections/{name}
   Body: { "name": "new-name" }
   ```

### Prioriteit
🟢 **Laag** - Nice to have voor toekomstige versies

---


## Samenvatting Prioriteiten

### 🔴 Hoog (gerealiseerd)
1. **`document_count` toevoegen aan Collection response** ✅
   - Voorkomt N+1 query probleem
   - Direct impact op UX

### 🟡 Medium (gewenst voor goede UX)
2. **Metadata velden in Document response** (`language`, `description`) ✅
3. **Upload response consistentie**

### 🟢 Laag (nice to have)
4. **Document List response format verduidelijking**
5. **Bulk operations** (toekomstige features)

---

## Vragen?

Als er vragen zijn over deze verzoeken of als jullie andere suggesties hebben, laat het ons weten! We zijn flexibel en kunnen onze UI aanpassen aan jullie API design keuzes.

**Contact:** Upload UI Team

---

## Bijlage: Volledige Gewenste Schema's

### Collection Schema
```typescript
{
  id: number
  name: string
  document_count: number
  created_at: string (ISO 8601)
}
```

### Document Schema
```typescript
{
  id: number
  file_name: string
  collection: string
  product_name: string | null
  row_count: number
  column_names: string[]
  language: string | null
  description: string | null
  attribute_descriptions: object | null
  created_at: string (ISO 8601)
}
```
