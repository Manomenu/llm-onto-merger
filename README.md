# LLM Ontology Merger

Narzędzie CLI do scalania dwóch ontologii OWL z wykorzystaniem lokalnego LLM (Ollama). Pipeline dzieli ontologie na małe, kontekstowo spójne środowiska scalania, wysyła je do modelu językowego, a następnie łączy wyniki w jedną ontologię.

---

## Instalacja

```bash
uv sync
```

Skopiuj `.env.example` → `.env` i ustaw zmienne środowiskowe (patrz sekcja Konfiguracja).

## Użycie

```bash
uv run llm-onto-merger --base base.owl --candidate candidate.owl --output out/
```

Pełne opcje:

```
--base         ścieżka do ontologii bazowej (OWL/RDF)
--candidate    ścieżka do ontologii kandydackiej (OWL/RDF)
--alignment-tool  narzędzie do alignmentu (domyślnie: aml)
--output       katalog wyjściowy (domyślnie: tests/outputs)
--max-env-chars   max rozmiar środowiska w znakach (domyślnie: 10 000)
```

## Konfiguracja

Plik `.env`:

```
OLLAMA_MODEL=llama3      # nazwa modelu w Ollama
OLLAMA_HOST=http://localhost:11434  # opcjonalnie
PARALLEL_LLM_REQUEST_COUNT=4        # ile równoległych zapytań do LLM
DEBUG=false                         # true → zapisuje pliki HTML z wizualizacjami
```

---

## Workflow — szczegółowy opis

Poniżej opisany jest kompletny przepływ danych od wejścia (dwa pliki `.owl`) do wyjścia (`merged_ontology.owl`).

### 1. Wczytanie argumentów (`load_arguments.py`)

Parsowane są argumenty CLI i walidowane ścieżki do plików wejściowych. Wynikiem jest `LoadedArguments` — Pydantic model przechowujący wszystkie parametry sesji.

---

### 2. Załadowanie ontologii (`ontology/graph.py` → `create_ontology`)

Każda ontologia jest wczytywana przez `rdflib` z pliku OWL/RDF do obiektu `Graph`. Następuje preprocessing:

- **Relabelowanie encji** — jeśli encja ma przypisany `rdfs:label`, jej lokalny fragment URI (część po `#` lub `/`) jest zastępowany wartością etykiety (spacje → `_`), po czym triplet `rdfs:label` jest usuwany. Cel: zamiast generycznych identyfikatorów jak `Class_42`, LLM widzi semantyczne nazwy jak `MedicalProcedure`. Encje, których docelowe URI jest już zajęte, są pomijane.

Po tym kroku oba grafy (`onto_1`, `onto_2`) zawierają wyłącznie semantycznie nazwane encje bez nadmiarowych etykiet.

---

### 3. Alignment (`alignment/aml_alignment.py`)

Wywoływane jest narzędzie **AgreementMakerLight (AML)** jako proces Java. AML analizuje obie ontologie i produkuje plik EDOAL (XML) z listą par encji, które uznaje za powiązane.

Każdy alignment ma postać:
```
Alignment(entity1=URI, entity2=URI, measure=0.0–1.0, relation="="|"<"|">"|...)
```

- `entity1` — encja z onto_1
- `entity2` — odpowiadająca encja z onto_2
- `measure` — siła dopasowania (0 = brak podobieństwa, 1 = identyczne)
- `relation` — typ relacji (`=` znaczy tożsamość konceptualna, `<`/`>` subklasa)

Wynikiem jest lista `list[Alignment]` posortowana później malejąco po `measure`.

---

### 4. Naiwny merge (baseline) (`ontology/merge.py` → `apply_alignments`)

Tworzona jest prosta unia obu grafów, gdzie dla każdego alignmentu `entity2` jest "złożone" w `entity1` — wszystkie triplety `entity2` są przepisywane na `entity1`. Wynik zapisywany jest jako `applied_alignments.owl` w katalogu wyjściowym.

**Po co:** To nie jest wynikowy merge. To punkt odniesienia — baseline, który można porównać z wynikiem LLM, żeby ocenić jakość scalania.

---

### 5. Budowanie namespace codec (`merge_environment.py` → `build_namespace_codec`)

Namespace'y zbierane są ze **wszystkich pozycji** w tripletach obu ontologii (subject, predicate, object). Następnie dokładane są well-known NS (`owl`, `rdf`, `rdfs`, `xsd`, `swrl`, `protege`, ...) — tylko te, których nie ma już w danych. Każdemu unikalnemu namespace'owi przypisywany jest krótki kod leksykograficzny (`aa, ab, ac, ..., az, ba, bb, ...`):

```
http://cmt#                              →  aa
http://ekaw#                             →  ab
http://www.w3.org/1999/02/22-rdf-syntax-ns#  →  ae
http://www.w3.org/2002/07/owl#           →  ah
...
zz  →  http://merged#   ← zarezerwowany dla encji tworzonych przez LLM
```

Kod `zz` jest zawsze zarezerwowany i pomijany w sekwencji — służy jako namespace dla zupełnie nowych encji, które LLM może wprowadzić podczas scalania.

Zwracane struktury:
- `uri_to_code` — pełne URI podmiotu → kod (dla `graph_to_string`)
- `code_to_ns` — kod → prefix NS (do dekodowania odpowiedzi LLM)
- `ns_to_code` — prefix NS → kod (do sprawdzania well-known przez kod zamiast string-prefix)
- `well_known_codes` — frozenset kodów well-known NS

Codec jest budowany **raz** wspólnie dla obu ontologii przed ekstrakcją i przekazywany w dół przez cały pipeline.

---

### 6. Ekstrakcja środowisk scalania (`extract_environments/module.py`)

To jest centralny, najbardziej złożony krok. Celem jest podzielenie obu ontologii na małe pary podgrafów (`MergeEnvironment`), które można niezależnie wysłać do LLM.

#### 6a. Kopiowanie do roboczych grafów `source_1`, `source_2`

Oba grafy są kopiowane do lokalnych kopii roboczych. Podczas ekstrakcji triplety są **przenoszone** (nie kopiowane) z `source_1`/`source_2` do podgrafów środowisk. Po zakończeniu ekstrakcji to co zostało w `source_1`/`source_2` to **leftovers** — encje bez żadnego alignmentu.

#### 6b. BFS dla każdego alignmentu (od najwyższego measure)

Alignmenty są przetwarzane od największego `measure` do najmniejszego (najlepsze dopasowania pierwsze). Dla każdego alignmentu:

**Seed:** Encja z onto_1 (`seed1`) i odpowiadająca z onto_2 (`seed2`) stają się punktem startowym ekspansji.

**BFS (przeszukiwanie wszerz):** Z seeda rozchodzi się "fala" ekspansji — każdy sąsiad encji jest kandydatem do dołączenia do środowiska. Przetwarzane są dwie kolejki równolegle: `expand_queue1` (strona onto_1) i `expand_queue2` (strona onto_2).

Dla każdego kandydata BFS sprawdza:

1. **Well-known namespace?** (np. `owl:Class`, `rdf:type`) → trafia do `border` (granicy środowiska), nie jest ekspandowany. Well-known NSy to słownik RDF/OWL, nie encje domenowe.

2. **Globalnie zamrożony?** — węzły, które były na granicy wcześniej ukończonego środowiska i nie mają już alignmentu, są "zamrożone" — trafiają do granicy, nie są ponownie ekspandowane. Zapobiega to duplikowaniu encji w wielu środowiskach.

3. **Jest w puli alignmentów?** → konieczna jest **paired expansion**: obaj partnerzy z obu stron muszą wejść razem. Sprawdzana jest łączna delta rozmiaru. Jeśli przekroczyłaby limit — alignment jest z powrotem wstawiany do puli (stanie się seedem własnego środowiska) i ekspansja kończy się.

4. **Zwykły węzeł?** → estymowana jest delta rozmiaru (ile znaków doda ta encja do prompta). Jeśli mieści się w limicie — triplety encji są przenoszone do podgrafu środowiska.

**Limit rozmiaru (`max_chars`):** Każde środowisko ma ograniczenie na liczbę znaków serializacji KG2Code. Limit zapobiega przekroczeniu okna kontekstu LLM. Rozmiar jest liczony przyrostowo podczas BFS (`_EnvSizeTracker`).

**Border:** Węzły, które znaleziono jako sąsiadów, ale nie weszły do wnętrza środowiska (z powodu limitu, zamrożenia lub well-known) trafiają do `border1`/`border2`. Granica jest przekazywana do LLM jako kontekst — model wie, że środowisko jest fragmentem większej ontologii i z jakimi innymi encjami jest połączone.

**Wynik:** `(environments: list[MergeEnvironment], onto_1_leftover: Graph, onto_2_leftover: Graph)`

- `environments` — lista środowisk scalania zasilanych alignmentami
- `onto_1_leftover`, `onto_2_leftover` — to co zostało w `source_1`, `source_2` po wyczerpaniu wszystkich alignmentów: encje bez żadnego dopasowania. Trafiają do outputu bez zmian (pass-through).

---

### 7. Serializacja do KG2Code (`merge_environment.py` → `to_string`)

Każde `MergeEnvironment` jest serializowane do formatu KG2Code. **Każdy URIRef w każdej pozycji tripletu** — subject, predicate, object — jest zakodowany jako `code:LocalName`:

```python
Entity('aa:Person', tuples=[
    ('aa:Person', 'ah:subClassOf', 'ab:Animal'),
    ('aa:Person', 'ae:type', 'ah:Class'),
])
```

Dzięki temu każdy element tripletu jest w pełni dekodowalny: `code_to_ns["ah"] + "subClassOf"` → `http://www.w3.org/2002/07/owl#subClassOf`. Literały (stringi, liczby) zapisywane są bez kodowania. Węzły graniczne też są kodowane. Alignmenty doklejane są jako osobna sekcja:

```
[Ontology_1]:
Entity('aa:Researcher', tuples=[('aa:Researcher', 'ah:subClassOf', 'aa:Person'), ...])
...
[Border_1]:
aa:Animal, ab:Organization

[Ontology_2]:
Entity('ab:Author', tuples=[...])
...
[Border_2]:
aa:Person

[Alignments]:
Researcher ↔ Researcher (relation: =)
```

`to_string()` zwraca `(prompt: str, code_to_ns: dict)`. Słownik jest potrzebny do dekodowania odpowiedzi LLM.

---

### 8. Scalanie przez LLM (`merge_environments/module.py` + `agent.py`)

Środowiska są wysyłane **równolegle** do LLM przez `asyncio.gather`, z ograniczeniem przez semafor (`parallel_llm_request_count`).

Agent Ollama dostaje prompt z KG2Code i instrukcję, która nakazuje mu:
- dotrzymać alignmentów (obowiązkowe scalenia)
- zachować relacje do wszystkich węzłów z Border_1 i Border_2
- usunąć redundantne encje (np. dwie nazwy tego samego konceptu)
- naprawić niespójności domenowe (np. usunąć błędne relacje is-a)
- wprowadzić nowe relacje cross-ontology tam gdzie ma to sens domenowy
- zminimalizować orphan classes (klasy bez superklasy)

LLM odpowiada w formacie JSON (`MergedOntology.model_json_schema()`):
```json
{
  "Merged_Ontology": [
    {"uri": "aa:Researcher", "tuples": [["aa:Researcher", "ah:subClassOf", "aa:Person"], ...]}
  ]
}
```

Encja ma tylko `uri` (w formacie `code:LocalName`) i `tuples` — nie ma osobnego pola `name`, bo nazwa jest już osadzona w `uri`. LLM może użyć `zz:NowaNazwa` dla zupełnie nowych konceptów.

`entities_to_graph(entities, code_to_ns)` dekoduje każdy element przez `_decode(coded, code_to_ns)`:
- `"aa:Researcher"` → `URIRef("http://cmt#Researcher")`
- `"ah:subClassOf"` → `URIRef("http://www.w3.org/2002/07/owl#subClassOf")`
- `"zz:NewConcept"` → `URIRef("http://merged#NewConcept")`
- `"some string"` (brak kodu) → `Literal("some string")`

Triplety z predykatem nie będącym URIRef są pomijane.

---

### 9. Debug output (`debug/`)

Gdy `DEBUG=true`, po zakończeniu mergowania generowane są pliki HTML z wizualizacjami (`pyvis`):

| Plik | Zawartość |
|------|-----------|
| `debug_pre_merge.html` | Wszystkie środowiska przed scalaniem + leftovers (onto_1 i onto_2) — kolory: niebieski (onto_1), pomarańczowy (onto_2), zielony (granica), czerwony (seed alignmentu) |
| `debug_merge_env_N.html` | Pojedyncze środowisko N przed scalaniem; różowe krawędzie = triplety które znikną po merge |
| `debug_post_merge.html` | Wszystkie scalone środowiska + leftovers w jednym widoku |
| `debug_merged_env_N.html` | Scalone środowisko N; różowe krawędzie = triplety dodane przez LLM |
| `onto_1_leftover.html` | Grafowa wizualizacja onto_1 leftover |
| `onto_2_leftover.html` | Grafowa wizualizacja onto_2 leftover |
| `env_diff_N.txt` | Tekstowy diff dla środowiska N: które triplety LLM usunął, które dodał |

---

### 10. Integracja (`integrate_environments.py`)

Wszystkie scalone podgrafy (`merged_environments`) plus `onto_1_leftover` i `onto_2_leftover` są łączone w jeden `rdflib.Graph` przez unię tripletów.

---

### 11. Zapis wyniku (`ontology/graph.py` → `save_ontology`)

Końcowy graf jest serializowany do formatu RDF/XML i zapisywany jako `merged_ontology.owl` w katalogu wyjściowym.

---

## Pliki wyjściowe

```
<output>/
  merged_ontology.owl       — wynikowa ontologia
  applied_alignments.owl    — baseline: naiwna unia z alignmentami (do porównania)
  debug_pre_merge.html      — (DEBUG=true) wizualizacja przed scalaniem
  debug_post_merge.html     — (DEBUG=true) wizualizacja po scalaniu
  debug_merge_env_N.html    — (DEBUG=true) środowisko N pre-merge
  debug_merged_env_N.html   — (DEBUG=true) środowisko N post-merge
  onto_1_leftover.html      — (DEBUG=true) encje bez alignmentu z onto_1
  onto_2_leftover.html      — (DEBUG=true) encje bez alignmentu z onto_2
  env_diff_N.txt            — (DEBUG=true) diff tripletów dla środowiska N
```

---

## Architektura

```
main.py
└── LLMOntologyMerger.merge()
    ├── create_ontology(onto_1)           # wczytaj + relabeluj
    ├── create_ontology(onto_2)
    ├── AlignmentModule.create_alignment() # AML → lista Alignment
    ├── apply_alignments()                # baseline merge → applied_alignments.owl
    ├── build_namespace_codec()           # wspólny codec URI → kody aa/ab/...
    ├── ExtractEnvironmentsModule.extract()
    │   ├── _pre_rename_onto2()           # entity2 → entity1 dla = alignmentów
    │   └── _build_merge_environment() × N  # BFS z limitem rozmiaru
    │       └── → MergeEnvironment (onto_1_sub, onto_2_sub, border, alignments)
    ├── MergeEnvironmentsModule.merge() × N  [równolegle]
    │   ├── env.to_string()               # → KG2Code prompt
    │   ├── merge_agent.run()             # → Ollama LLM
    │   └── entities_to_graph()           # → rdflib.Graph
    ├── save_pre_merge_debug()            # (DEBUG) HTML wizualizacje
    ├── save_post_merge_debug()
    ├── save_diff_debug()
    ├── integrate_environments()          # unia wszystkich grafów + leftovers
    └── save_ontology()                   # → merged_ontology.owl
```

## Wymagania

- Python 3.11+
- Java (do uruchamiania AML)
- Ollama z zainstalowanym modelem
- AML jar w `thirdparty/aml/AgreementMakerLight.jar`
