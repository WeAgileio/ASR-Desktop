import unittest
from asr_service.drive import Drive, DriveError, FOLDER, content_version


class FakeDrive(Drive):
    def __init__(self):
        self.items = {
            "src": {
                "id": "src",
                "mimeType": FOLDER,
                "capabilities": {"canListChildren": True},
            },
            "dst": {
                "id": "dst",
                "mimeType": FOLDER,
                "driveId": "shared",
                "capabilities": {"canAddChildren": True},
            },
            "sub": {
                "id": "sub",
                "name": "folder",
                "mimeType": FOLDER,
                "parents": ["src"],
            },
        }
        self.tree = {"src": [self.items["sub"]], "sub": []}

    def metadata(self, id):
        return self.items[id]

    def children(self, id):
        yield from self.tree[id]


class DriveTest(unittest.TestCase):
    def test_preflight(self):
        d = FakeDrive()
        d.preflight("src", "dst")
        d.items["dst"].pop("driveId")
        with self.assertRaises(DriveError):
            d.preflight("src", "dst")

    def test_nested_sort_skip_and_read_failure(self):
        d = FakeDrive()

        def media(id, name):
            return {
                "id": id,
                "name": name,
                "mimeType": "video/mp4",
                "size": "10",
                "md5Checksum": "a",
                "capabilities": {"canDownload": True},
            }

        d.tree["sub"] = [
            media("file10", "clip10.mp4"),
            media("file2", "clip2.mp4"),
            {
                "id": "shortcut",
                "name": "shortcut",
                "mimeType": "application/vnd.google-apps.shortcut",
            },
            {
                "id": "out",
                "name": "result",
                "mimeType": FOLDER,
                "appProperties": {"asrResult": "1"},
            },
        ]
        files, skip = d.scan("src", "dst")
        self.assertEqual([f["id"] for f in files], ["file2", "file10"])
        self.assertEqual(skip, 2)
        d.tree["sub"][0]["capabilities"]["canDownload"] = False
        with self.assertRaises(DriveError):
            d.scan("src", "dst")

    def test_rename_does_not_change_version(self):
        self.assertEqual(
            content_version({"name": "old", "md5Checksum": "a"}),
            content_version({"name": "new", "md5Checksum": "a"}),
        )

    def test_destination_ancestor_rejected(self):
        d = FakeDrive()
        d.items["src"]["parents"] = ["dst"]
        with self.assertRaises(DriveError):
            d.preflight("src", "dst")

    def test_pagination_and_incomplete_search(self):
        class Response:
            def __init__(self, p):
                self.p = p

            def json(self):
                return self.p

        pages = iter(
            [
                {"files": [{"id": "one"}], "nextPageToken": "next"},
                {"files": [{"id": "two"}]},
            ]
        )
        d = Drive(session=object())
        d.request = lambda *a, **k: Response(next(pages))
        self.assertEqual(list(d.children("src")), [{"id": "one"}, {"id": "two"}])
        d.request = lambda *a, **k: Response({"incompleteSearch": True})
        with self.assertRaises(DriveError):
            list(d.children("src"))


if __name__ == "__main__":
    unittest.main()
