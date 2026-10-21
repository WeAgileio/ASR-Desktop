import copy
import unittest
import hashlib
import json
from pathlib import Path
import tempfile

from asr_srt.errors import ValidationError
from asr_srt.registry import catalog, execution, registration, validate_options
from asr_desktop.models import ModelStore, ModelError


class RegistryTests(unittest.TestCase):
    def test_legacy_and_compatible_registration(self):
        source = catalog()
        legacy = registration("paraformer", source)
        self.assertEqual(legacy["execution"]["engine"], "funasr-paraformer")
        custom = copy.deepcopy(legacy)
        custom["id"] = "custom-weights"
        source["models"].append(custom)
        self.assertEqual(registration("custom-weights", source)["execution"], legacy["execution"])

    def test_unknown_engine_and_unsafe_paths_rejected(self):
        value = registration("paraformer")
        value["execution"]["engine"] = "arbitrary.python"
        with self.assertRaises(ValidationError):
            execution(value)
        value = registration("paraformer")
        value["execution"]["required_files"]["paraformer"] = ["../weights"]
        with self.assertRaises(ValidationError):
            execution(value)

    def test_cpu_only_and_hotwords_capabilities(self):
        value = registration("paraformer")
        value["execution"].update(devices=["cpu"], hotwords=False)
        validate_options(value, "auto", ())
        validate_options(value, "cpu", ())
        for device, words in (("gpu", ()), ("mps", ()), ("cpu", ("test",))):
            with self.assertRaises(ValidationError):
                validate_options(value, device, words)

    def test_execution_changes_snapshot_and_accepted_definition_stays_pinned(self):
        source = catalog()
        with tempfile.TemporaryDirectory() as directory:
            store = ModelStore(Path(directory), source)
            pinned = store.definition("breeze-asr-25")
            old_revision = pinned["snapshot_id"]
            updated = copy.deepcopy(source)
            item = next(m for m in updated["models"] if m["id"] == "breeze-asr-25")
            item["execution"]["parameters"]["num_beams"] = 2
            components = {key: updated["components"][key] for key in item["components"]}
            item["snapshot_id"] = hashlib.sha256(json.dumps({"components": components, "execution": item["execution"]},
                sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            current = ModelStore(Path(directory), updated)
            self.assertNotEqual(current.definition("breeze-asr-25")["snapshot_id"], old_revision)
            self.assertEqual(current.definition(old_revision)["execution"]["parameters"]["num_beams"], 1)
            self.assertEqual(pinned["execution"]["parameters"]["num_beams"], 1)
            # Tampering with the saved execution settings cannot keep its identity.
            pinned["execution"]["parameters"]["num_beams"] = 3
            with self.assertRaises(ModelError):
                ModelStore._validate_definition(pinned)

    def test_all_catalog_assets_and_required_files_are_complete(self):
        source = catalog()
        for item in source["models"]:
            spec = execution(item)
            components = {key: source["components"][key] for key in item["components"]}
            ModelStore._validate_definition(dict(item, component_definitions=components))
            self.assertEqual(item["download_bytes"], sum(a["size"] for c in components.values() for a in c["assets"]))
            for key, files in spec["required_files"].items():
                self.assertTrue(set(files) <= {a["path"] for a in components[key]["assets"]})
