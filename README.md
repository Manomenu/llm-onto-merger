# Ontology Merging System

A CLI application that merges OWL ontologies using Microsoft Agent Framework and Foundry.

## Installation

1. Install dependencies with `uv`:
```bash
uv sync
```

2. Copy `.env.example` to `.env` and fill in your Foundry project details.

## Usage

```bash
uv run llm-onto-merger -- --base <base-ontology-path> --candidate <candidate-ontology-path> --mappings <mappings-path> --output <output-path>
```

Example:
```bash
uv run llm-onto-merger -- --base base.owl --candidate candidate.owl --mappings mappings.txt --output merged.owl
```

The application uses a workflow with an executor agent that prepares the ontologies and a merger agent that performs the merging based on the mappings.

## Requirements

- Python 3.10+
- Azure Foundry project with GPT-4o deployment
- Azure CLI logged in (`az login`)