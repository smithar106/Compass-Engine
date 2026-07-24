import json


class ExtractionValidator:

    REQUIRED_ACCEPT_FIELDS = [
        "organization_name", "problem_statement",
        "intervention_title", "outcomes"
    ]

    def validate_schema(self, extraction: dict) -> dict:
        errors = []
        if not isinstance(extraction, dict):
            return {"valid": False, "errors": ["Extraction is not a JSON object"]}

        if "has_intervention" not in extraction:
            errors.append("Missing has_intervention field")
        if not isinstance(extraction.get("outcomes"), list):
            errors.append("outcomes must be a list")

        for field in ["result_status", "intervention_families", "source_passages"]:
            if field not in extraction:
                errors.append(f"Missing {field} field")

        return {"valid": len(errors) == 0, "errors": errors}

    def validate_minimum_viability(self, extraction: dict) -> dict:
        errors = []

        has_org = bool(extraction.get("organization_name"))
        has_problem = bool(extraction.get("problem_statement"))
        has_intervention = bool(extraction.get("intervention_title"))
        has_outcome = bool(len(extraction.get("outcomes", [])) > 0)
        has_passages = bool(len(extraction.get("source_passages", [])) > 0)

        missing = []
        if not has_org:
            missing.append("organization_name")
        if not has_problem:
            missing.append("problem_statement")
        if not has_intervention:
            missing.append("intervention_title")
        if not has_outcome:
            missing.append("outcomes")
        if not has_passages:
            missing.append("source_passages")

        viable = has_org and has_problem and has_intervention and has_outcome

        return {
            "viable": viable,
            "missing_required": missing,
            "has_org": has_org,
            "has_problem": has_problem,
            "has_intervention": has_intervention,
            "has_outcome": has_outcome,
            "has_passages": has_passages,
        }

    def validate_field_level(self, extraction: dict) -> dict:
        fields = {}
        for outcome in extraction.get("outcomes", []):
            for key in ["metric_name", "value_type", "source_passage"]:
                if not outcome.get(key):
                    fields.setdefault("missing_outcome_fields", []).append(key)

        if extraction.get("implementation_cost"):
            if not extraction["implementation_cost"].get("source_passage"):
                fields.setdefault("missing_passages", []).append("implementation_cost")

        if extraction.get("implementation_duration"):
            if not extraction["implementation_duration"].get("source_passage"):
                fields.setdefault("missing_passages", []).append("implementation_duration")

        vendor_flags = []
        if extraction.get("is_vendor_reported"):
            vendor_flags.append("vendor_reported")

        if extraction.get("independently_verified") is False:
            vendor_flags.append("not_independently_verified")

        return {
            "vendor_flags": vendor_flags,
            "missing_passages": fields.get("missing_passages", []),
            "missing_outcome_fields": fields.get("missing_outcome_fields", []),
            "field_count": len(extraction.get("outcomes", [])),
            "passage_count": len(extraction.get("source_passages", [])),
        }

    def validate(self, extraction: dict) -> dict:
        schema_check = self.validate_schema(extraction)
        if not schema_check["valid"]:
            return {"decision": "reject", "reason": "schema_validation_failed",
                    "errors": schema_check["errors"],
                    "schema_check": schema_check}

        viability = self.validate_minimum_viability(extraction)
        field_level = self.validate_field_level(extraction)

        if not viability["viable"]:
            return {"decision": "quarantine",
                    "reason": f"missing_required_fields: {viability['missing_required']}",
                    "viability": viability, "field_level": field_level}

        contradictory = self._check_contradictions(extraction)
        if contradictory:
            return {"decision": "quarantine",
                    "reason": f"contradictory_fields: {contradictory}",
                    "contradictions": contradictory,
                    "viability": viability, "field_level": field_level}

        return {"decision": "accept", "reason": "all_checks_passed",
                "viability": viability, "field_level": field_level}

    def _check_contradictions(self, extraction: dict) -> list:
        contradictions = []
        for outcome in extraction.get("outcomes", []):
            if outcome.get("baseline_value") and outcome.get("post_value"):
                b, p = outcome["baseline_value"], outcome["post_value"]
                delta = outcome.get("absolute_change")
                pct = outcome.get("percentage_change")
                if delta is not None and abs((b - p)) != abs(delta):
                    contradictions.append(
                        f"Outcome '{outcome.get('metric_name')}': baseline {b}, post {p}, "
                        f"absolute_change {delta} does not match"
                    )
        return contradictions

    def validate_batch(self, documents: list) -> list:
        validated = []
        for doc in documents:
            extraction = doc.get("extraction", {})
            result = self.validate(extraction)
            validated.append({
                "document_id": doc.get("document_id"),
                "title": doc.get("title", ""),
                "validation": result["decision"],
                "reason": result.get("reason", ""),
                "details": result,
            })
        return validated
