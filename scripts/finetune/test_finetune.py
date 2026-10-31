"""Tests for the fine-tuning kit that need no model download: a toy tokenizer stands in for Qwen's.
Run: python -m unittest scripts.finetune.test_finetune"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
from transformers import PreTrainedTokenizerFast

from scripts.finetune import build_sft_dataset, eval_adapter, hardware, tokenize_data, train_lora
from scripts.finetune.common import ROOT, facts_messages, golden_record, target_text

# Same structure as Qwen3.5's template: ChatML turns, and with enable_thinking=False an empty think block.
TEMPLATE = (
    "{%- for m in messages %}{{- '<|im_start|>' + m.role + '\\n' + m.content + '<|im_end|>\\n' }}{%- endfor %}"
    "{%- if add_generation_prompt %}{{- '<|im_start|>assistant\\n' }}"
    "{%- if enable_thinking is defined and enable_thinking is false %}{{- '<think>\\n\\n</think>\\n\\n' }}"
    "{%- else %}{{- '<think>\\n' }}{%- endif %}{%- endif %}"
)


def toy_tokenizer() -> PreTrainedTokenizerFast:
    specials = ["<|im_start|>", "<|im_end|>", "<think>", "</think>"]
    tk = Tokenizer(models.BPE(unk_token=None, byte_fallback=False))
    tk.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tk.decoder = decoders.ByteLevel()
    corpus = ['{"scope": [{"text": "Supply 5 units", "pages": [4]}]} system user assistant think hello world ' * 5]
    tk.train_from_iterator(corpus, trainers.BpeTrainer(vocab_size=300, special_tokens=specials,
                                                       initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    return PreTrainedTokenizerFast(tokenizer_object=tk, chat_template=TEMPLATE)


MESSAGES = [{"role": "system", "content": "You are a summarizer."}, {"role": "user", "content": "hello world"},
            {"role": "assistant", "content": '{"scope": [{"text": "Supply 5 units", "pages": [4]}]}'}]


class TestMasking(unittest.TestCase):
    def setUp(self):
        self.tok = toy_tokenizer()

    def test_prompt_ends_like_inference_with_think_off(self):
        self.assertTrue(tokenize_data.prompt_text(self.tok, MESSAGES).endswith("<|im_start|>assistant\n<think>\n\n</think>\n\n"))

    def test_prompt_tokens_are_masked_and_answer_tokens_are_learned(self):
        ex = tokenize_data.build_example(self.tok, MESSAGES, 4096)
        ids, labels, n = ex["input_ids"], ex["labels"], ex["prompt_tokens"]
        self.assertTrue(all(l == tokenize_data.IGNORE for l in labels[:n]), "prompt tokens must not be learned")
        self.assertEqual(labels[n:], ids[n:], "every answer token is learned")
        self.assertEqual(self.tok.decode(ids[n:]), MESSAGES[2]["content"] + "<|im_end|>")  # answer, then the stop token
        self.assertEqual(labels[-1], self.tok.convert_tokens_to_ids("<|im_end|>"))
        # the system prompt, the user turn and the empty think block are all inside the masked part
        masked = self.tok.decode(ids[:n])
        for part in ("You are a summarizer.", "hello world", "<think>"):
            self.assertIn(part, masked)

    def test_too_long_is_dropped_and_listed_not_truncated(self):
        self.assertIsNone(tokenize_data.build_example(self.tok, MESSAGES, 10))
        kept, dropped = tokenize_data.encode_all(self.tok, [{"doc_id": "d", "messages": MESSAGES}], 10)
        self.assertEqual((kept, [d["doc_id"] for d in dropped]), ([], ["d"]))


class TestKit(unittest.TestCase):
    def test_target_is_parsed_back_by_the_apps_own_parser(self):
        from backend.llm.executive_summary.agent import parse_agent_response

        rec = golden_record(sorted(p.stem for p in (ROOT / "summaries").glob("*.json"))[0])
        parsed = parse_agent_response(target_text(rec["summary"]), rec["summary"]["issuing_organization"]).model_dump()
        for key in build_sft_dataset.__dict__.get("TARGET_KEYS", []) or ["overview", "scope", "important_conditions"]:
            self.assertEqual(parsed[key], rec["summary"][key])

    def test_facts_prompt_is_the_agents_prompt(self):
        from backend.llm.executive_summary.prompts import EXECUTIVE_SUMMARY_AGENT_SYSTEM_PROMPT, build_agent_user_prompt

        agg = {"overview": [], "issuing_organization": "Ünïcode Ltd"}
        msgs = facts_messages(agg)
        self.assertEqual(msgs[0]["content"], EXECUTIVE_SUMMARY_AGENT_SYSTEM_PROMPT)
        self.assertEqual(msgs[1]["content"], build_agent_user_prompt(json.dumps(agg, indent=2, ensure_ascii=False)))

    def test_val_choice_is_deterministic_and_sticky(self):
        sectors = {f"d{i}": s for i, s in enumerate("AABBCCDD")}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(build_sft_dataset, "SFT_DIR", Path(d)):
            first = build_sft_dataset.choose_val(sorted(sectors), sectors)
            self.assertEqual(len(first), 3)
            self.assertEqual(len({sectors[x] for x in first}), 3, "val covers different sectors")
            self.assertEqual(build_sft_dataset.choose_val(sorted(sectors), sectors), first)
            more = sorted(sectors) + ["d9"]
            sectors["d9"] = "E"
            self.assertEqual(build_sft_dataset.choose_val(more, sectors), first, "new docs do not reshuffle val")

    def test_pickle_scan_rejects_pickle_style_files(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "adapter_model.safetensors").write_bytes(b"x")
            train_lora.pickle_scan(Path(d))  # fine
            (Path(d) / "optimizer.pt").write_bytes(b"x")
            with self.assertRaises(SystemExit):
                train_lora.pickle_scan(Path(d))

    def test_memory_estimate_grows_with_length_and_shrinks_with_4bit(self):
        shape = hardware.KNOWN["Qwen/Qwen3.5-4B"]
        short, long_ = (hardware.estimate_gib(shape, n, 2000, True)["total"] for n in (4096, 32768))
        self.assertLess(short, long_)
        self.assertLess(long_, hardware.estimate_gib(shape, 32768, 2000, False)["total"])


class TestEval(unittest.TestCase):
    def test_a_golden_summary_scores_perfectly_against_itself(self):
        doc_id = sorted(p.stem for p in (ROOT / "summaries").glob("*.json"))[0]
        golden = golden_record(doc_id)["summary"]
        r = eval_adapter.score(golden, golden, doc_id)
        self.assertEqual((r["schema_valid"], r["limits_ok"], r["condition_prefix_ok"], r["similarity_mean"], r["length_ratio"]),
                         (1, 1, 1, 1.0, 1.0))
        self.assertEqual(r["bullets_with_page"], 1.0)
        self.assertEqual(eval_adapter.score(None, golden, doc_id), {"schema_valid": 0})

    def test_refuses_when_an_eval_doc_was_trained_on(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "MANIFEST.json").write_text(json.dumps({"doc_ids": {"train": ["a", "x"], "val": ["b"], "eval": []}}))
            with mock.patch.object(eval_adapter, "SFT_DIR", Path(d)):
                eval_adapter.refuse_if_leaking({"c"}, None)  # fine
                with self.assertRaises(SystemExit):
                    eval_adapter.refuse_if_leaking({"c", "x"}, None)


if __name__ == "__main__":
    unittest.main()
