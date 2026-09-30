"""Ingestion tests: parsing, coercion, quarantine, and money units."""

from __future__ import annotations

import json
import unittest

from helpers import EngineTestCase, db, ingest


ASSETS_CSV = (
    "asset_id,name,asset_type,business_unit,criticality,daily_revenue,exposure_class,status\n"
    "A-NEW,New server,server,IT,3,50000,internal,active\n"
)

EXISTING_ASSET = "A1-OMS-DB-PROD"


class TestAssetIngest(EngineTestCase):
    def test_clean_upload_commits_every_row(self):
        result = ingest.ingest(self.conn, "assets", "a.csv", ASSETS_CSV.encode())
        self.assertEqual(result.status, "committed")
        self.assertEqual(result.rows_ok, 1)
        self.assertEqual(result.rows_quarantined, 0)
        self.assertTrue(self.conn.execute(
            "SELECT 1 FROM assets WHERE asset_id='A-NEW'").fetchone())

    def test_money_is_converted_from_rupees_to_minor_units(self):
        ingest.ingest(self.conn, "assets", "a.csv", ASSETS_CSV.encode())
        stored = self.conn.execute(
            "SELECT daily_revenue FROM assets WHERE asset_id='A-NEW'").fetchone()[0]
        self.assertEqual(stored, 50_000 * 100)

    def test_action_cost_is_converted_to_minor_units(self):
        csv_bytes = (
            "action_code,name,cost,effect_type,effect_json\n"
            "ACT-NEW,New action,75000,control_ce,\"{\"\"control_code\"\":\"\"C04\"\"}\"\n"
        ).encode()
        ingest.ingest(self.conn, "actions", "a.csv", csv_bytes)
        stored = self.conn.execute(
            "SELECT cost FROM actions WHERE action_code='ACT-NEW'").fetchone()[0]
        self.assertEqual(stored, 75_000 * 100)

    def test_loss_component_value_is_converted_to_minor_units(self):
        csv_bytes = (
            "scenario_code,component_code,basis,value,hours,record_count\n"
            "S1,LC-NEW,fixed_amount,250000,,100\n"
        ).encode()
        ingest.ingest(self.conn, "loss_components", "lc.csv", csv_bytes)
        stored = self.conn.execute(
            "SELECT value FROM loss_components WHERE component_code='LC-NEW'"
        ).fetchone()[0]
        self.assertEqual(stored, 250_000 * 100)

    def test_bad_row_is_quarantined_and_good_rows_still_load(self):
        csv_bytes = (
            "asset_id,name,asset_type,business_unit,criticality\n"
            "A-OK,Fine,server,IT,3\n"
            ",Missing id,server,IT,3\n"
            "A-BAD,Bad criticality,server,IT,99\n"
        ).encode()
        result = ingest.ingest(self.conn, "assets", "a.csv", csv_bytes)
        self.assertEqual(result.rows_ok, 1)
        self.assertEqual(result.rows_quarantined, 2)
        self.assertTrue(self.conn.execute(
            "SELECT 1 FROM assets WHERE asset_id='A-OK'").fetchone())

    def test_quarantine_records_point_at_the_real_dataset(self):
        csv_bytes = (
            "asset_id,name,asset_type,business_unit,criticality\n"
            ",Missing id,server,IT,3\n"
        ).encode()
        result = ingest.ingest(self.conn, "assets", "a.csv", csv_bytes)
        rows = self.conn.execute(
            "SELECT dataset_id, payload_json, reason FROM quarantine").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dataset_id"], result.dataset_id)
        self.assertTrue(rows[0]["reason"])

    def test_quarantine_keeps_the_source_line_number(self):
        csv_bytes = (
            "asset_id,name,asset_type,business_unit,criticality\n"
            "A-OK,Fine,server,IT,3\n"
            ",Missing id,server,IT,3\n"
        ).encode()
        ingest.ingest(self.conn, "assets", "a.csv", csv_bytes)
        row = self.conn.execute("SELECT payload_json FROM quarantine").fetchone()
        self.assertEqual(json.loads(row["payload_json"])["__line__"], 3)

    def test_enum_violation_is_quarantined(self):
        csv_bytes = (
            "asset_id,name,asset_type,business_unit,criticality,exposure_class\n"
            "A-BAD,Bad class,server,IT,3,teleported\n"
        ).encode()
        result = ingest.ingest(self.conn, "assets", "a.csv", csv_bytes)
        self.assertEqual(result.rows_ok, 0)
        self.assertEqual(result.rows_quarantined, 1)

    def test_out_of_range_number_is_quarantined(self):
        csv_bytes = (
            "asset_id,name,asset_type,business_unit,criticality,daily_revenue\n"
            "A-BAD,Negative money,server,IT,3,-5\n"
        ).encode()
        result = ingest.ingest(self.conn, "assets", "a.csv", csv_bytes)
        self.assertEqual(result.rows_quarantined, 1)

    def test_dry_run_reports_rows_without_writing(self):
        result = ingest.ingest(self.conn, "assets", "a.csv", ASSETS_CSV.encode(),
                               commit=False)
        self.assertEqual(result.status, "validated")
        self.assertEqual(result.rows_ok, 1)
        self.assertFalse(self.conn.execute(
            "SELECT 1 FROM assets WHERE asset_id='A-NEW'").fetchone())
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM quarantine").fetchone()[0], 0)

    def test_reingesting_the_same_row_updates_instead_of_duplicating(self):
        ingest.ingest(self.conn, "assets", "a.csv", ASSETS_CSV.encode())
        result = ingest.ingest(self.conn, "assets", "a.csv", ASSETS_CSV.encode())
        self.assertEqual(result.rows_updated, 1)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM assets WHERE asset_id='A-NEW'"
                              ).fetchone()[0], 1)

    def test_unknown_dataset_type_is_rejected(self):
        with self.assertRaises(ingest.IngestError):
            ingest.ingest(self.conn, "spaceships", "a.csv", ASSETS_CSV.encode())

    def test_empty_file_is_rejected(self):
        result = ingest.ingest(self.conn, "assets", "a.csv", b"")
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.rows_ok, 0)

    def test_file_with_only_an_empty_row_is_rejected(self):
        result = ingest.ingest(self.conn, "assets", "a.csv",
                               b"asset_id,name,asset_type,business_unit,criticality\n"
                               b",,,,,\n")
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.rows_ok, 0)


class TestFindingIngest(EngineTestCase):
    HEADER = ("external_finding_id,source_system,asset_id,severity,rule_id,exploitable\n")

    def test_finding_with_unknown_asset_is_quarantined(self):
        csv_bytes = (self.HEADER +
                     "F-1,scanner,ASSET-DOES-NOT-EXIST,high,TEST-1,1\n").encode()
        result = ingest.ingest(self.conn, "findings", "f.csv", csv_bytes)
        self.assertEqual(result.rows_ok, 0)
        self.assertEqual(result.rows_quarantined, 1)
        self.assertIn("unmatched_asset", self.conn.execute(
            "SELECT reason FROM quarantine").fetchone()["reason"])

    def test_finding_for_a_known_asset_is_committed(self):
        csv_bytes = (self.HEADER +
                     f"F-1,scanner,{EXISTING_ASSET},high,TEST-1,1\n").encode()
        result = ingest.ingest(self.conn, "findings", "f.csv", csv_bytes)
        self.assertEqual(result.rows_ok, 1)
        self.assertEqual(result.rows_quarantined, 0)
        self.assertEqual(self.conn.execute(
            "SELECT asset_id FROM findings WHERE external_finding_id='F-1'"
        ).fetchone()["asset_id"], EXISTING_ASSET)

    def test_mixed_finding_file_commits_the_valid_row(self):
        csv_bytes = (self.HEADER +
                     f"F-1,scanner,{EXISTING_ASSET},high,TEST-1,1\n"
                     "F-2,scanner,ASSET-NOPE,high,TEST-2,1\n"
                     f"F-3,scanner,{EXISTING_ASSET},not-a-severity,TEST-3,0\n"
                     ).encode()
        result = ingest.ingest(self.conn, "findings", "f.csv", csv_bytes)
        self.assertEqual(result.rows_ok, 1)
        self.assertEqual(result.rows_quarantined, 2)

    def test_finding_can_be_matched_by_hostname(self):
        csv_bytes = (self.HEADER +
                     "F-2,scanner,,high,TEST-2,1\n").encode()
        self.conn.execute(
            "UPDATE findings SET status='open'")
        result = ingest.ingest(self.conn, "findings", "f.csv",
                               b"external_finding_id,source_system,hostname,severity,rule_id,exploitable\n"
                               b"F-HOST,scanner,oms-db-prod.corp.example.com,high,TEST-H,1\n")
        self.assertEqual(result.rows_ok, 1)
        self.assertEqual(self.conn.execute(
            "SELECT asset_id FROM findings WHERE external_finding_id='F-HOST'"
        ).fetchone()["asset_id"], EXISTING_ASSET)

    def test_json_upload_is_accepted(self):
        payload = json.dumps([{
            "external_finding_id": "F-J1", "source_system": "scanner",
            "asset_id": EXISTING_ASSET, "severity": "medium", "rule_id": "TEST-J",
            "exploitable": 0,
        }]).encode()
        result = ingest.ingest(self.conn, "findings", "f.json", payload)
        self.assertEqual(result.rows_ok, 1)
        self.assertTrue(self.conn.execute(
            "SELECT 1 FROM findings WHERE external_finding_id='F-J1'").fetchone())


class TestActionValidation(EngineTestCase):
    def test_invalid_effect_json_is_quarantined(self):
        csv_bytes = (
            "action_code,name,cost,effect_type,effect_json\n"
            "ACT-BAD,Bad json,1000,control_ce,not-json\n"
        ).encode()
        result = ingest.ingest(self.conn, "actions", "a.csv", csv_bytes)
        self.assertEqual(result.rows_quarantined, 1)
        self.assertEqual(result.rows_ok, 0)

    def test_unknown_prerequisite_is_quarantined(self):
        csv_bytes = (
            "action_code,name,cost,effect_type,effect_json,requires_actions\n"
            "ACT-NEW,Needs ghost,1000,control_ce,\"{}\",ACT-GHOST\n"
        ).encode()
        result = ingest.ingest(self.conn, "actions", "a.csv", csv_bytes)
        self.assertEqual(result.rows_quarantined, 1)
        self.assertIn("ACT-GHOST", self.conn.execute(
            "SELECT reason FROM quarantine").fetchone()["reason"])


class TestScenarioIngest(EngineTestCase):
    def test_scenario_for_unknown_asset_is_quarantined(self):
        csv_bytes = (
            "scenario_code,name,asset_id,p0,exposure_factor\n"
            "S-NEW,New scenario,ASSET-NOPE,0.05,1.0\n"
        ).encode()
        result = ingest.ingest(self.conn, "scenarios", "s.csv", csv_bytes)
        self.assertEqual(result.rows_quarantined, 1)

    def test_scenario_p0_above_the_cap_is_quarantined(self):
        from app import config
        csv_bytes = (
            "scenario_code,name,asset_id,p0,exposure_factor\n"
            f"S-NEW,Too likely,{EXISTING_ASSET},{config.MAX_ANNUAL_PROBABILITY * 10},1.0\n"
        ).encode()
        result = ingest.ingest(self.conn, "scenarios", "s.csv", csv_bytes)
        self.assertEqual(result.rows_quarantined, 1)


class TestDatasetAudit(EngineTestCase):
    def test_dataset_row_is_recorded_for_every_upload(self):
        result = ingest.ingest(self.conn, "assets", "a.csv", ASSETS_CSV.encode())
        row = self.conn.execute(
            "SELECT * FROM datasets WHERE id=?", (result.dataset_id,)).fetchone()
        self.assertEqual(row["dataset_type"], "assets")
        self.assertEqual(row["rows_total"], 1)
        self.assertEqual(row["rows_ok"], 1)
        self.assertTrue(row["filename"])

    def test_ingest_is_documented_as_synthetic_when_flagged(self):
        result = ingest.ingest(self.conn, "assets", "a.csv", ASSETS_CSV.encode(),
                               synthetic=True)
        self.assertTrue(self.conn.execute(
            "SELECT synthetic FROM assets WHERE asset_id='A-NEW'").fetchone()["synthetic"])


if __name__ == "__main__":
    unittest.main()
