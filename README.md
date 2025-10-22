# Pixie Tabular DB

Deze repo bevat de service die Excel/CSV-bestanden opslaat en ontsluit binnen PiXie.  
Kerntaken:
- maakt per upload een collectie aan en bewaart elk tabblad als afzonderlijke dataset;
- houdt de data klaar in PostgreSQL zodat `pixie-recommender` er queries op kan draaien;
- levert eenvoudige API’s (`/collections`, `/documents`, `/query`) voor andere PiXie-services.

Gebruik: Upload UI stuurt tabulaire bestanden naar deze service → Recommender vraagt later de rijen en kolommen op → Chat UI toont het resultaat aan de gebruiker.
