import json
import threading
import unittest
import urllib.request

from paperdesk.domain.errors import InvalidInput, ProviderFailed
from paperdesk.domain.models import PaperMetadata
from paperdesk.infrastructure.scholarly import ArxivIndex, OpenAlexIndex
from paperdesk.ports.scholarly import ScholarlyIndex
from paperdesk.services.bibtex import bibtex
from paperdesk.web.server import create_server

from .helpers import make_pdf
from .test_reader_services import FakeDownloader, ScriptedProvider, scripted_app

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom"><entry>
<id>http://arxiv.org/abs/1706.03762v7</id><title>Attention Is All You Need</title><summary>The dominant models.</summary>
<published>2017-06-12T17:57:34Z</published><author><name>Ashish Vaswani</name></author><author><name>Noam Shazeer</name></author>
<arxiv:doi>10.48550/arXiv.1706.03762</arxiv:doi><arxiv:primary_category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
</entry></feed>"""
WORK = {"display_name": "Attention Is All You Need", "publication_year": 2017, "doi": "https://doi.org/10.65215/2q58a426",
        "authorships": [{"author": {"display_name": "Ashish Vaswani"}}],
        "primary_location": {"source": {"display_name": "Neural Information Processing Systems"}},
        "primary_topic": {"field": {"display_name": "Computer Science"}, "subfield": {"display_name": "Artificial Intelligence"}}}
FIRST_PAGE = "arXiv:1706.03762v7 [cs.CL] 2 Aug 2023\nAttention Is All You Need\nAshish Vaswani Google Brain\nAbstract The dominant"


class Index(ScholarlyIndex):
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def lookup(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0) if self.results else None
        if isinstance(result, Exception):
            raise result
        return result


class LookupParsingTests(unittest.TestCase):
    def test_arxiv_reads_doi_and_primary_category(self):
        found = ArxivIndex(FakeDownloader({"https://export.arxiv.org/api/query": ATOM})).lookup(title="", arxiv_id="1706.03762")
        self.assertEqual((found.arxiv_id, found.doi, found.field), ("1706.03762", "10.48550/arXiv.1706.03762", "cs.CL"))

    def test_openalex_prefers_the_most_cited_of_identical_titles(self):
        copy = {**WORK, "doi": "https://doi.org/10.5281/zenodo.1", "cited_by_count": 0,
                "authorships": [{"author": {"display_name": "Someone Else"}}]}
        downloader = FakeDownloader({"https://api.openalex.org/works?": json.dumps({"results": [copy, {**WORK, "cited_by_count": 120000}]})})
        self.assertEqual(OpenAlexIndex(downloader).lookup(title="Attention is all you need").authors, "Ashish Vaswani")

    def test_openalex_reads_bare_doi_and_field(self):
        downloader = FakeDownloader({"https://api.openalex.org/works?": json.dumps({"results": [WORK]})})
        found = OpenAlexIndex(downloader).lookup(title="Attention is all you need")
        self.assertEqual((found.doi, found.venue, found.field),
                         ("10.65215/2q58a426", "Neural Information Processing Systems", "Computer Science / Artificial Intelligence"))


class PaperInfoTests(unittest.TestCase):
    def setUp(self):
        self.app, tmp = scripted_app()
        self.addCleanup(tmp.cleanup)
        self.doc, _ = self.app.library.import_pdf("1706.03762v7.pdf", make_pdf(["x"]))
        self.app.library.save_text(self.doc.id, [FIRST_PAGE])

    def service(self, *indexes):
        from paperdesk.services.paper_info import PaperInfoService
        return PaperInfoService(self.app.library, list(indexes))

    def test_identifier_on_the_first_page_and_details_merged_across_indexes(self):
        arxiv = Index(PaperMetadata("Attention Is All You Need", "", "Ashish Vaswani, Noam Shazeer", "2017", "", source="arxiv",
                                    arxiv_id="1706.03762", doi="10.48550/arXiv.1706.03762", field="cs.CL"))
        openalex = Index(PaperMetadata("Attention Is All You Need", "", "Ashish Vaswani", "2017", "Neural Information Processing Systems",
                                       source="openalex", doi="10.65215/2q58a426", field="Computer Science / Artificial Intelligence"))
        doc = self.service(arxiv, openalex).refresh(self.doc.id)
        self.assertEqual(arxiv.calls[0]["arxiv_id"], "1706.03762")
        self.assertEqual(openalex.calls[0]["title"], "Attention Is All You Need")  # the found title, not the file name
        self.assertEqual((doc.authors, doc.year, doc.venue, doc.doi, doc.arxiv_id, doc.field),
                         ("Ashish Vaswani, Noam Shazeer", "2017", "Neural Information Processing Systems",
                          "10.48550/arXiv.1706.03762", "1706.03762", "cs.CL"))
        self.assertTrue(doc.info_checked_at)
        self.assertEqual(self.app.library.get(self.doc.id).venue, "Neural Information Processing Systems")  # stored
        self.service(arxiv, openalex).refresh(self.doc.id)
        self.assertEqual(len(arxiv.calls), 1)  # checked once; force=True looks it up again

    def test_arxiv_listing_is_not_a_venue_and_a_preprint_doi_from_openalex_is_skipped(self):
        listing = Index(PaperMetadata("Attention Is All You Need", "", venue="arXiv (Cornell University)", year="2017",
                                      source="openalex", doi="10.48550/arxiv.1706.03762"))
        doc = self.service(listing).refresh(self.doc.id)
        self.assertEqual((doc.venue, doc.doi, doc.year), ("", "", "2017"))
        reupload = Index(PaperMetadata("Attention Is All You Need", "", "Ashish Vaswani", "2025", source="openalex", doi="10.65215/2q58a426"))
        self.assertEqual(self.service(reupload).refresh(self.doc.id, force=True).doi, "")
        published = Index(PaperMetadata("Attention Is All You Need", "", "Ashish Vaswani", "2017", "Neural Information Processing Systems",
                                        source="openalex", doi="10.5555/3295222.3295349"))
        self.assertEqual(self.service(published).refresh(self.doc.id, force=True).doi, "10.5555/3295222.3295349")

    def test_a_match_whose_title_or_first_author_is_not_on_the_page_is_ignored(self):
        cited = Index(PaperMetadata("Neural Machine Translation by Jointly Learning to Align", "", "Dzmitry Bahdanau", "2014"))
        doc = self.service(cited).refresh(self.doc.id)
        self.assertEqual((doc.authors, bool(doc.info_checked_at)), ("", True))
        namesake = Index(PaperMetadata("Attention is all you need", "", "Beat Döbeli Honegger", "2026"))
        self.assertEqual(self.service(namesake).refresh(self.doc.id, force=True).authors, "")

    def test_offline_lookup_is_retried_later(self):
        doc = self.service(Index(InvalidInput("offline")), Index(InvalidInput("offline"))).refresh(self.doc.id)
        self.assertIsNone(doc.info_checked_at)

    def test_found_title_replaces_only_the_file_name(self):
        index = Index(PaperMetadata("Attention  Is All You Need", "", "Ashish Vaswani", "2017"),
                      PaperMetadata("Attention Is All You Need", "", "Ashish Vaswani", "2017"))
        self.assertEqual(self.service(index).refresh(self.doc.id).title, "Attention Is All You Need")  # was "1706.03762v7"
        self.app.library.rename(self.doc.id, "Transformer")
        doc = self.service(index).refresh(self.doc.id, force=True)
        self.assertEqual((doc.title, doc.authors), ("Transformer", "Ashish Vaswani"))  # a chosen title stays


class OrganizerTests(unittest.TestCase):
    def setUp(self):
        self.app, tmp = scripted_app()
        self.addCleanup(tmp.cleanup)
        self.doc, _ = self.app.library.import_pdf("a.pdf", make_pdf(["x"]))
        self.app.library.save_text(self.doc.id, [FIRST_PAGE])
        self.ml = self.app.folders.create("Machine Learning")
        self.nlp = self.app.folders.create("NLP", self.ml.id)

    def reply(self, folder_id="", new_folder=""):
        ScriptedProvider.replies.append(json.dumps({"folder_id": folder_id, "new_folder": new_folder}))

    def test_existing_folder(self):
        self.reply(self.nlp.id)
        result = self.app.organizer.organize(self.doc.id, "Korean")
        self.assertEqual((result["folder"]["id"], result["created"]), (self.nlp.id, False))
        self.assertEqual(self.app.library.get(self.doc.id).folder_id, self.nlp.id)
        prompt = ScriptedProvider.prompts[0]
        self.assertIn(f"{self.nlp.id}: Machine Learning / NLP", prompt.user)
        self.assertIn("Attention Is All You Need", prompt.user)
        self.assertIn("written in Korean", prompt.user)
        self.assertEqual(prompt.response_schema["required"], ["folder_id", "new_folder"])

    def test_new_folder_is_created_once(self):
        self.reply(new_folder="강화학습")
        result = self.app.organizer.organize(self.doc.id, "Korean")
        self.assertTrue(result["created"])
        self.assertEqual(result["folder"]["name"], "강화학습")
        other, _ = self.app.library.import_pdf("b.pdf", make_pdf(["y"]))
        self.reply(new_folder="  강화학습 ")
        again = self.app.organizer.organize(other.id, "Korean")
        self.assertEqual((again["folder"]["id"], again["created"]), (result["folder"]["id"], False))
        self.assertEqual(len(ScriptedProvider.prompts), 2)  # never answered from the cache

    def test_paper_in_a_folder_stays_and_unusable_reply_fails(self):
        self.reply("not-a-folder")
        with self.assertRaises(ProviderFailed):
            self.app.organizer.organize(self.doc.id, "English")
        self.assertIsNone(self.app.library.get(self.doc.id).folder_id)
        self.app.library.move(self.doc.id, self.ml.id)
        result = self.app.organizer.organize(self.doc.id, "English")
        self.assertIsNone(result["folder"])
        self.assertEqual(len(ScriptedProvider.prompts), 1)


class BibtexTests(unittest.TestCase):
    def doc(self, **values):
        from paperdesk.domain.models import Document
        return Document("id", values.pop("title", "Attention Is All You Need"), "a.pdf", "sha", 1, "now", **values)

    def test_entry_types_keys_and_escaping(self):
        text = bibtex([
            self.doc(authors="Ashish Vaswani, Noam Shazeer", year="2017", venue="Neural Information Processing Systems",
                     arxiv_id="1706.03762", field="cs.CL"),
            self.doc(authors="Ashish Vaswani", year="2017", doi="10.1/x"),
            self.doc(title="Q&A on 100% {data}", authors="Kaiming He", year="2016", venue="IEEE Transactions on Pattern Analysis",
                     field="Computer Science / Artificial Intelligence")])
        entries = text.split("\n\n")
        self.assertTrue(entries[0].startswith("@inproceedings{vaswani2017attention,\n"))
        self.assertIn("  author = {Ashish Vaswani and Noam Shazeer}", entries[0])
        self.assertIn("  booktitle = {Neural Information Processing Systems}", entries[0])
        self.assertIn("  primaryClass = {cs.CL}", entries[0])
        self.assertTrue(entries[1].startswith("@misc{vaswani2017attentionb,\n"))
        self.assertIn("  doi = {10.1/x}", entries[1])
        self.assertTrue(entries[2].startswith("@article{he2016q,\n"))
        self.assertIn("  title = {Q\\&A on 100\\% data}", entries[2])
        self.assertNotIn("primaryClass", entries[2])
        self.assertEqual(bibtex([]), "")


class EndpointTests(unittest.TestCase):
    def test_info_organize_and_bibtex(self):
        index = Index(PaperMetadata("Attention Is All You Need", "", "Ashish Vaswani", "2017", "Neural Information Processing Systems"))
        app, tmp = scripted_app(scholarly=index)
        self.addCleanup(tmp.cleanup)
        server = create_server(app, "127.0.0.1", 0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        doc, _ = app.library.import_pdf("a.pdf", make_pdf(["x"]))
        app.library.save_text(doc.id, [FIRST_PAGE])

        def post(path, body):
            request = urllib.request.Request(server.url.rstrip("/") + path, data=json.dumps(body).encode(), method="POST",
                                             headers={"X-Paperdesk": "1", "X-Paperdesk-Lang": "ko", "Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)

        self.assertEqual(post(f"/api/documents/{doc.id}/info", {})["document"]["year"], "2017")
        ScriptedProvider.replies.append(json.dumps({"folder_id": "", "new_folder": "자연어 처리"}))
        organized = post(f"/api/documents/{doc.id}/organize", {})
        self.assertEqual(organized["folder"]["name"], "자연어 처리")
        self.assertIn("written in Korean", ScriptedProvider.prompts[-1].user)  # the display language
        self.assertIn("@inproceedings{vaswani2017attention,", post("/api/bibtex", {"ids": [doc.id]})["bibtex"])
        self.assertEqual(len(index.calls), 1)


if __name__ == "__main__":
    unittest.main()
