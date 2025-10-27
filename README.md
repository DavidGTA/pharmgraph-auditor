# **PharmGraph-Auditor**

This repository contains the implementation of **PharmGraph-Auditor**.

After installing the environment and completing your configuration file at `config/settings.yaml`,
you can upload markdown files of pharmaceutical documents, where each section is marked with `##` headings.

You can build your **Hybrid Pharmaceutical Knowledge Base (HPKB)** using the following commands:

```bash
python tools/run_single_task.py -t extract_metadata -f ./data/input_markdowns/阿贝西利片.md
python tools/run_single_task.py -t extract_composition -f ./data/input_markdowns/阿贝西利片.md -k drug_canonical_name=阿贝西利片
python tools/run_single_task.py -t extract_indication -f ./data/input_markdowns/阿贝西利片.md -k drug_canonical_name=阿贝西利片
python tools/run_single_task.py -t extract_contraindication -f ./data/input_markdowns/阿贝西利片.md -k drug_canonical_name=阿贝西利片 active_ingredient_name=阿贝西利
python tools/run_single_task.py -t extract_dosage_rules -f ./data/input_markdowns/阿贝西利片.md -k drug_canonical_name=阿贝西利片
python tools/run_single_task.py -t extract_administration_texts -f ./data/input_markdowns/阿贝西利片.md -k drug_canonical_name=阿贝西利片
python tools/run_single_task.py -t extract_special_populations -f ./data/input_markdowns/阿贝西利片.md -k drug_canonical_name=阿贝西利片
python tools/run_single_task.py -t extract_drug_interactions -f ./data/input_markdowns/阿贝西利片.md -k drug_canonical_name=阿贝西利片
python tools/save_to_db.py 阿贝西利片
```

After building your HPKB, you can audit prescription cases with the following command:

```bash
python cov_audit/run_audit_pipeline.py ./data/audit_cases/阿贝西利片/cases.json
```