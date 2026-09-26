import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validatectf", ROOT / "bin" / "validatectf.py")
validatectf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validatectf)


class ValidateCtfTests(unittest.TestCase):
    def test_tcode_round_trip(self):
        epoch = 1790380000
        tcode = validatectf.makeTCode(epoch)
        self.assertEqual(validatectf.decodeTCode(tcode), str(epoch))

    def test_vcode_is_stable_sha256(self):
        tcode = validatectf.makeTCode(1790380000)
        actual = validatectf.makeVCode(
            "test-secret", tcode, "player1", "42", "Correct", "100", "25", "0", "0"
        )
        self.assertEqual(len(actual), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in actual))
        self.assertEqual(
            actual,
            validatectf.makeVCode(
                "test-secret", tcode, "player1", "42", "Correct", "100", "25", "0", "0"
            ),
        )

    def test_invalid_tcode_rejected(self):
        with self.assertRaises(ValueError):
            validatectf.decodeTCode("xyz")

    def test_bytes_supported_for_compatibility(self):
        tcode = validatectf.makeTCode(1790380000)
        value = validatectf.makeVCode(
            b"secret", tcode.encode(), b"u", b"1", b"Correct", b"1", b"0", b"0", b"0"
        )
        self.assertEqual(len(value), 64)


if __name__ == "__main__":
    unittest.main()
