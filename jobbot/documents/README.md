# Put your documents here

`setup.py` reads everything in this folder (and, if it finds nothing here, the
folder above the project). Supported: **PDF, DOCX, TXT, MD**.

What helps, in order of value:

| Document | What it gives the tool |
|---|---|
| **CV / résumé** | Required. Name, contacts, city, languages, career stage, job titles, and the bullet points that become your cover-letter evidence. |
| **Transcripts** | The graded strength/weakness layer — which subjects you demonstrably did well in. This is what separates two postings that both look "relevant". |
| **Certificates** | Attached to every application pack. Language certificates also confirm the level read off your CV. |
| **Reference letters** | Attached to application packs. |

Files are classified automatically by their name and contents, so no particular
naming scheme is needed. A scanned PDF with no text layer is still attached to
your applications; it just cannot be analysed. Run OCR over it first if you
want its contents used.

Nothing here is uploaded anywhere. Everything `setup.py` does is local text
matching against the ontology in `jobbot/ontology/`.
