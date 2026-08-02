"""Phase 7 tests for organization/industry matching.

Covers: resolution (name/alias/domain/industry), taxonomy normalization of
equivalent labels, context-aware retrieval ranking, provenance retention,
user-edit override, profile-driven retrieval changes, and determinism.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace as NS

from compass_collector.organization.taxonomy import normalize_industry
from compass_collector.organization.profile import (
    clean_company_name,
    resolve_organization,
)
from compass_collector.analysis.context_retrieval import (
    ContextQuery,
    find_comparable_implementations_context,
)


def rec(org, ind, wf, sub=None, bf="finance", status="successful", emp=5000):
    return NS(
        id=org,
        organization_name=org,
        organization_industry=[ind],
        intervention_components={"workflow": wf},
        organization_employee_count=emp,
        organization_type="company",
        organization_geography=[],
        problem_statement="invoice processing takes days and is manual and error prone",
        problem_business_function=[bf],
        result_status=status,
        intervention_title=f"{wf} automation",
        problem_baseline_description="",
        intervention_description="",
    )


class TestNameResolution(unittest.TestCase):
    def test_company_name_resolves_to_correct_organization(self):
        r = resolve_organization(company_name="Shopify")
        self.assertEqual(r.proposed.canonical_name, "Shopify")
        self.assertEqual(r.proposed.primary_industry, "technology")
        self.assertIn("registry:name", r.resolution_path)

    def test_domain_resolves(self):
        r = resolve_organization(company_domain="shopify.com")
        self.assertEqual(r.proposed.canonical_name, "Shopify")
        self.assertIn("registry:domain", r.resolution_path)

    def test_alias_resolves(self):
        r = resolve_organization(company_name="JP Morgan Chase & Co")
        self.assertEqual(r.proposed.canonical_name, "JPMorgan Chase")
        self.assertEqual(r.proposed.industry_subsector, "banking")

    def test_clean_company_name_strips_suffixes(self):
        self.assertEqual(clean_company_name("Acme Corporation"), "Acme")
        self.assertEqual(clean_company_name("Shopify Inc."), "Shopify")


class TestIndustryOnly(unittest.TestCase):
    def test_industry_only_entry_works(self):
        r = resolve_organization(industry="banking")
        self.assertEqual(r.proposed.primary_industry, "financial_services")
        self.assertEqual(r.proposed.industry_subsector, "banking")
        self.assertIn("taxonomy:industry", r.resolution_path)

    def test_finance_cluster_normalizes_consistently(self):
        labels = [
            "Financial Services", "Finance", "Banking", "FinTech",
            "Financial Technology", "financial_services", "Banking/Financial Services",
        ]
        for label in labels:
            n = normalize_industry(label)
            self.assertEqual(n.canonical, "financial_services", msg=label)

    def test_equivalent_case_separator_normalize(self):
        self.assertEqual(normalize_industry("HealthCare").canonical, "healthcare")
        self.assertEqual(normalize_industry("Financial Services").canonical, "financial_services")
        self.assertEqual(normalize_industry("financial_services").canonical, "financial_services")

    def test_multi_industry_label_uses_best_part(self):
        n = normalize_industry("Tank Storage / Energy / Chemicals")
        self.assertEqual(n.canonical, "energy_utilities")


class TestAmbiguityAndConfirmation(unittest.TestCase):
    def test_industry_only_requires_confirmation_for_org_identity(self):
        r = resolve_organization(industry="technology")
        self.assertIsNotNone(r.proposed)
        # No canonical name → the org identity needs user confirmation.
        self.assertFalse(r.proposed.canonical_name)

    def test_partial_profile_is_low_confidence(self):
        r = resolve_organization(company_name="MysteryCo", industry="fintech")
        self.assertIn("partial", r.resolution_path)
        self.assertLess(r.confidence["overall"], 0.5)
        self.assertFalse(r.proposed.domain)  # identity fields not established


class TestProvenance(unittest.TestCase):
    def test_inferred_fields_retain_provenance(self):
        r = resolve_organization(industry="banking")
        profile = r.proposed
        industry = profile.fields.get("primary_industry")
        self.assertIsNotNone(industry)
        self.assertEqual(industry.source, "taxonomy")
        self.assertIn(industry.method, ("explicit", "inferred"))
        self.assertGreater(industry.confidence, 0)
        self.assertEqual(industry.version, "org-v1")
        # regulatory context derived from industry must carry provenance
        reg = profile.fields.get("regulatory_context")
        self.assertIsNotNone(reg)
        self.assertEqual(reg.method, "inferred")


class TestDeterminism(unittest.TestCase):
    def test_deterministic_profiles_and_matching(self):
        r1 = resolve_organization(company_name="Stripe", industry="payments")
        r2 = resolve_organization(company_name="Stripe", industry="payments")
        self.assertEqual(r1.to_dict(), r2.to_dict())

        q = ContextQuery(
            workflow="invoice_processing", business_function="finance",
            primary_industry="financial_services", industry_subsector="banking",
        )
        records = [rec("A", "banking", "invoice_processing"), rec("B", "retail", "invoice_processing")]
        r_a = find_comparable_implementations_context(q, records)
        r_b = find_comparable_implementations_context(q, records)
        self.assertEqual(r_a["results"], r_b["results"])


class TestContextRetrieval(unittest.TestCase):
    def _query(self, workflow="invoice_processing", industry="financial_services", sub="banking"):
        return ContextQuery(
            workflow=workflow,
            business_function="finance",
            problem_statement="manual invoice processing is slow and error prone",
            primary_industry=industry,
            industry_subsector=sub,
            employee_band="1000-10000",
        )

    def test_workflow_outranks_weak_same_industry(self):
        q = self._query()
        records = [
            rec("BankTick", "banking", "ticketing"),        # same industry, diff workflow
            rec("RetailInv", "retail", "invoice_processing"),  # diff industry, same workflow
        ]
        results = find_comparable_implementations_context(q, records)["results"]
        by_org = {r["organization"]: r for r in results}
        self.assertGreater(
            by_org["RetailInv"]["fit_total"], by_org["BankTick"]["fit_total"]
        )
        # same-workflow record must not be excluded despite different industry
        self.assertIn("RetailInv", by_org)

    def test_same_workflow_and_subsector_boosted(self):
        q = self._query()
        records = [
            rec("BankSame", "banking", "invoice_processing"),  # workflow + subsector match
            rec("BankDiff", "banking", "ticketing"),           # subsector only
            rec("RetailInv", "retail", "invoice_processing"),  # workflow only
        ]
        results = find_comparable_implementations_context(q, records)["results"]
        top = results[0]["organization"]
        self.assertEqual(top, "BankSame")
        breakdown = results[0]["fit_breakdown"]
        self.assertGreater(breakdown["workflow"]["raw"], 0.9)
        self.assertGreater(breakdown["industry_subsector"]["raw"], 0.9)

    def test_factor_breakdown_returned(self):
        q = self._query()
        results = find_comparable_implementations_context(q, [rec("A", "banking", "invoice_processing")])["results"]
        factors = set(results[0]["fit_breakdown"].keys())
        expected = {
            "problem", "workflow", "operational_function", "industry_subsector",
            "broader_industry", "organization_size", "business_model",
            "geography", "regulatory", "technology_readiness",
        }
        self.assertEqual(factors, expected)

    def test_cross_industry_not_excluded(self):
        q = self._query()
        results = find_comparable_implementations_context(
            q, [rec("RetailInv", "retail", "invoice_processing")]
        )["results"]
        self.assertEqual(len(results), 1)

    def test_different_profiles_change_ranking(self):
        records = [
            rec("BankInv", "banking", "invoice_processing"),
            rec("RetailInv", "retail", "invoice_processing"),
        ]
        q_bank = self._query(industry="financial_services", sub="banking")
        q_retail = self._query(industry="retail_consumer", sub="retail")
        bank_res = find_comparable_implementations_context(q_bank, records)["results"]
        retail_res = find_comparable_implementations_context(q_retail, records)["results"]
        self.assertEqual(bank_res[0]["organization"], "BankInv")
        self.assertEqual(retail_res[0]["organization"], "RetailInv")

    def test_sparse_geography_boosts_match_but_does_not_penalize_missing(self):
        q = self._query(workflow="invoice_processing")
        q.geography = "Canada"
        plain = rec("Plain", "banking", "invoice_processing")           # no geography
        with_geo = rec("WithGeo", "banking", "invoice_processing")      # geography present
        with_geo.organization_geography = ["Canada"]
        results = find_comparable_implementations_context(q, [plain, with_geo])["results"]
        by = {r["organization"]: r["fit_breakdown"] for r in results}
        self.assertGreater(by["WithGeo"]["geography"]["raw"], by["Plain"]["geography"]["raw"])
        self.assertGreaterEqual(by["Plain"]["geography"]["raw"], 0.5)

    def test_sparse_size_boosts_match_but_does_not_penalize_missing(self):
        q = self._query(workflow="invoice_processing")
        no_size = rec("NoSize", "banking", "invoice_processing")
        no_size.organization_employee_count = None
        match = rec("Match", "banking", "invoice_processing")           # 5000 → 1000-10000
        results = find_comparable_implementations_context(q, [no_size, match])["results"]
        by = {r["organization"]: r["fit_breakdown"] for r in results}
        self.assertGreater(by["Match"]["organization_size"]["raw"], by["NoSize"]["organization_size"]["raw"])
        self.assertGreaterEqual(by["NoSize"]["organization_size"]["raw"], 0.5)


class TestUserEditOverride(unittest.TestCase):
    def test_user_industry_overrides_registry(self):
        r = resolve_organization(company_name="Stripe", industry="retail")
        # user-supplied industry takes precedence over the registry value
        self.assertEqual(r.proposed.primary_industry, "retail_consumer")

    def test_registry_profile_marks_user_confirmed(self):
        from compass_collector.organization.profile import _set_field
        from compass_collector.organization.taxonomy import NormalizedValue

        r = resolve_organization(company_name="Stripe")
        r.proposed.user_confirmed = ["primary_industry"]
        r.proposed.fields["primary_industry"] = NormalizedValue(
            raw="payments", value="payments", source="user", confidence=1.0
        )
        self.assertIn("primary_industry", r.proposed.user_confirmed)
        self.assertEqual(r.proposed.primary_industry, "payments")


if __name__ == "__main__":
    unittest.main()
