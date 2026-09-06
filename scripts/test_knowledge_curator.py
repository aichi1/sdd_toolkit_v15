#!/usr/bin/env python3
"""
test_knowledge_curator.py: knowledge_curator.py の回帰テスト（C-46）

C-46: retrospective JSON のキー名取り違えにより、教訓 → コンポーネント改善の
ループが全期間にわたって機能していなかった。3 箇所が壊れていた:

  1. retro["category"] / retro["lessons"]
     → 実際は metadata.category / lessons_learned（lessons が常に空）
  2. extract_lesson_keywords が description / context を読む
     → 実際は lesson / evidence / applicability（キーワードが常に 0 件）
  3. lesson_desc が str(lesson) にフォールバック
     → dict 全体が文字列化されて候補に入る

本テストは**両形式**（現行 lessons_learned / 旧 lessons）で候補が生成されることを守る。
"""
import unittest
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "knowledge_curator", str(Path(__file__).parent / "knowledge_curator.py")
)
kc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kc)


def _registry():
    """テスト用の最小レジストリ。"""
    return {"components": [
        {"id": "skill-alpha-v1", "name": "alpha", "category_origin": "small_implementation",
         "tags": ["pytest", "verification", "exit"]},
        {"id": "skill-beta-v1", "name": "beta", "category_origin": "research_report",
         "tags": ["pytest", "verification"]},
        {"id": "skill-gamma-v1", "name": "gamma", "category_origin": "research_report",
         "tags": ["unrelated"]},
    ]}


CURRENT_FORMAT = {
    "metadata": {"category": "small_implementation", "project_name": "p1"},
    "lessons_learned": [
        {"category": "process", "priority": "high",
         "lesson": "強制点は pytest で verification して exit code を確かめる",
         "evidence": "C-42 で exit code が読み飛ばされた",
         "applicability": "all projects"},
    ],
}

LEGACY_FORMAT = {
    "category": "small_implementation",
    "project_name": "p2",
    "lessons": [
        {"priority": "medium",
         "description": "強制点は pytest で verification して exit code を確かめる",
         "context": "旧形式のフィールド"},
    ],
}


class TestRetroFormatCompatibility(unittest.TestCase):
    """C-46: 現行形式と旧形式の両方から教訓とカテゴリを読めること。"""

    def test_current_format_category(self):
        self.assertEqual(kc.retro_category(CURRENT_FORMAT), "small_implementation")

    def test_legacy_format_category(self):
        self.assertEqual(kc.retro_category(LEGACY_FORMAT), "small_implementation")

    def test_current_format_lessons(self):
        self.assertEqual(len(kc.retro_lessons(CURRENT_FORMAT)), 1)

    def test_legacy_format_lessons(self):
        self.assertEqual(len(kc.retro_lessons(LEGACY_FORMAT)), 1)

    def test_missing_lessons_returns_empty_list(self):
        self.assertEqual(kc.retro_lessons({"metadata": {"category": "x"}}), [])

    def test_unknown_category_falls_back(self):
        self.assertEqual(kc.retro_category({}), "unknown")


class TestLessonText(unittest.TestCase):
    """C-46 (2)(3): 教訓の本文が現行形式のキーから組み立てられること。"""

    def test_current_format_text_is_not_empty(self):
        t = kc.lesson_text(CURRENT_FORMAT["lessons_learned"][0])
        self.assertIn("強制点", t)
        self.assertIn("C-42", t)          # evidence も含む

    def test_legacy_format_text_is_not_empty(self):
        t = kc.lesson_text(LEGACY_FORMAT["lessons"][0])
        self.assertIn("強制点", t)
        self.assertIn("旧形式", t)        # context も含む

    def test_text_is_not_stringified_dict(self):
        """旧実装は dict 全体を str() していた。"""
        t = kc.lesson_text(CURRENT_FORMAT["lessons_learned"][0])
        self.assertFalse(t.strip().startswith("{"))

    def test_non_dict_lesson_is_stringified(self):
        self.assertEqual(kc.lesson_text("plain string"), "plain string")


class TestKeywordExtraction(unittest.TestCase):
    """C-46 (2): キーワードが空にならないこと。一般語は除くこと。"""

    def test_keywords_are_not_empty(self):
        kws = kc.extract_lesson_keywords(CURRENT_FORMAT["lessons_learned"][0])
        self.assertGreater(len(kws), 0)
        self.assertIn("pytest", kws)

    def test_stopwords_are_excluded(self):
        kws = kc.extract_lesson_keywords(
            {"lesson": "this project with that quality criteria", "evidence": ""})
        for w in ("this", "with", "that", "quality", "criteria", "project"):
            self.assertNotIn(w, kws)

    def test_keywords_are_deduplicated(self):
        kws = kc.extract_lesson_keywords({"lesson": "pytest pytest pytest", "evidence": ""})
        self.assertEqual(kws.count("pytest"), 1)


class TestProjectName(unittest.TestCase):
    """C-46 (4): lesson_source が unknown にならないこと。"""

    def test_current_format(self):
        self.assertEqual(kc.retro_project_name(CURRENT_FORMAT), "p1")

    def test_legacy_format(self):
        self.assertEqual(kc.retro_project_name(LEGACY_FORMAT), "p2")

    def test_missing_falls_back(self):
        self.assertEqual(kc.retro_project_name({}), "unknown")

    def test_candidate_records_source(self):
        """生成された候補の lesson_source が unknown でないこと。"""
        c = kc.generate_improvement_candidates(CURRENT_FORMAT, _registry())
        self.assertTrue(c)
        self.assertNotEqual(c[0]["lesson_source"], "unknown")


class TestGeneralizableTags(unittest.TestCase):
    """C-46: プロジェクト固有 ID をタグ提案から除くこと。"""

    def test_issue_ids_are_excluded(self):
        tags = kc.generalizable_tags(["c-26", "binary", "r-08", "s-04", "gitattributes"])
        self.assertNotIn("c-26", tags)
        self.assertNotIn("r-08", tags)
        self.assertNotIn("s-04", tags)
        self.assertIn("binary", tags)

    def test_limit_is_respected(self):
        self.assertEqual(
            len(kc.generalizable_tags(["alpha", "beta", "gamma", "delta"])), 3)

    def test_words_that_merely_start_with_id_letters_are_kept(self):
        """課題 ID はハイフン付き。`c1234` や `delta` を誤って除外しない。"""
        tags = kc.generalizable_tags(["c1234", "delta", "d3js"], limit=5)
        self.assertIn("c1234", tags)
        self.assertIn("delta", tags)
        self.assertIn("d3js", tags)


class TestCandidateGeneration(unittest.TestCase):
    """C-46 の中核: 両形式で候補が 0 件にならないこと。"""

    def test_current_format_generates_candidates(self):
        c = kc.generate_improvement_candidates(CURRENT_FORMAT, _registry())
        self.assertGreater(len(c), 0, "現行形式（lessons_learned）で候補が 0 件になってはいけない")

    def test_legacy_format_generates_candidates(self):
        c = kc.generate_improvement_candidates(LEGACY_FORMAT, _registry())
        self.assertGreater(len(c), 0, "旧形式（lessons）で候補が 0 件になってはいけない")

    def test_candidate_description_is_readable(self):
        c = kc.generate_improvement_candidates(CURRENT_FORMAT, _registry())
        self.assertFalse(c[0]["lesson_description"].strip().startswith("{"))

    def test_per_lesson_cap_is_enforced(self):
        """1 教訓あたりの候補数に上限があること（絞り込みなしでは 1,500 件を超えた）。"""
        big = {"components": [
            {"id": f"skill-{i}", "name": f"s{i}", "category_origin": "small_implementation",
             "tags": []} for i in range(50)]}
        c = kc.generate_improvement_candidates(CURRENT_FORMAT, big)
        self.assertLessEqual(len(c), kc.MAX_CANDIDATES_PER_LESSON)

    def test_tag_match_requires_minimum_overlap(self):
        """共通キーワードが 1 件だけのコンポーネントは拾わない。"""
        reg = {"components": [
            {"id": "skill-one-tag", "name": "one", "category_origin": "other",
             "tags": ["pytest"]},                       # 共通 1 件 → 拾わない
            {"id": "skill-two-tags", "name": "two", "category_origin": "other",
             "tags": ["pytest", "verification"]},       # 共通 2 件 → 拾う
        ]}
        c = kc.generate_improvement_candidates(CURRENT_FORMAT, reg)
        ids = {x["component_id"] for x in c}
        self.assertNotIn("skill-one-tag", ids)
        self.assertIn("skill-two-tags", ids)

    def test_empty_lessons_generates_nothing(self):
        c = kc.generate_improvement_candidates({"metadata": {"category": "x"}}, _registry())
        self.assertEqual(len(c), 0)


class TestApplicabilityFiltering(unittest.TestCase):
    """C-53 / R-34: 教訓 → コンポーネント候補が applicability で絞り込まれること。

    実測（Phase 10 の retrospective 時）: 教訓 10 件が同一カテゴリの 5 スキル全部に
    無差別付与され、50 件の候補になった。applicability が「all projects」でない教訓は、
    タグの重なりが無い限りカテゴリ内の全コンポーネントに付与してはならない。
    """

    def _five_skills_same_category(self):
        return {"components": [
            {"id": f"skill-small-implementation-phase{i:02d}", "name": f"phase{i}",
             "category_origin": "small_implementation", "tags": ["unrelated-tag"]}
            for i in range(1, 6)
        ]}

    def test_is_broad_applicability_all_projects(self):
        self.assertTrue(kc.is_broad_applicability({"applicability": "all projects"}))

    def test_is_broad_applicability_missing_field(self):
        self.assertTrue(kc.is_broad_applicability({}))

    def test_is_broad_applicability_narrow_scope_is_false(self):
        self.assertFalse(kc.is_broad_applicability({"applicability": "self-modifying projects"}))

    def test_is_broad_applicability_is_case_insensitive_exact_match(self):
        self.assertTrue(kc.is_broad_applicability({"applicability": "All Projects"}))

    def test_is_broad_applicability_non_dict_lesson_defaults_broad(self):
        """文字列教訓（旧フォーマットの一部）は絞り込み情報が無いため従来どおり。"""
        self.assertTrue(kc.is_broad_applicability("plain string lesson"))

    def test_broad_applicability_matches_whole_category(self):
        """`applicability: all projects` は従来どおりカテゴリ全体に無差別マッチしてよい。"""
        lesson = {"priority": "high", "lesson": "強制点は pytest で確かめる",
                  "evidence": "", "applicability": "all projects"}
        retro = {"metadata": {"category": "small_implementation", "project_name": "p"},
                 "lessons_learned": [lesson]}
        c = kc.generate_improvement_candidates(retro, self._five_skills_same_category())
        self.assertEqual(len(c), kc.MAX_CANDIDATES_PER_LESSON)

    def test_narrow_applicability_does_not_blanket_match_category(self):
        """**負のテスト（C-53 の再発防止）**: 具体的な applicability はカテゴリ無差別付与を許さない。

        タグの重なりが無い場合、5 件のコンポーネント全部に候補が生成されてはならない
        （実測の 10 教訓 × 5 スキル = 50 件のパターンを 1 教訓単位で再現）。
        """
        lesson = {"priority": "high", "lesson": "自己変更プロジェクト固有の手順の教訓",
                  "evidence": "D-01 D-02", "applicability": "self-modifying projects"}
        retro = {"metadata": {"category": "small_implementation", "project_name": "p"},
                 "lessons_learned": [lesson]}
        c = kc.generate_improvement_candidates(retro, self._five_skills_same_category())
        self.assertEqual(len(c), 0)

    def test_narrow_applicability_still_matches_via_tag_overlap(self):
        """具体的な applicability でも、タグの重なりがあれば候補になってよい。"""
        lesson = {"priority": "high", "lesson": "pytest で verification して exit code を確かめる",
                  "evidence": "", "applicability": "self-modifying projects"}
        reg = {"components": [
            {"id": "skill-tag-match", "name": "m", "category_origin": "other",
             "tags": ["pytest", "verification"]},
            {"id": "skill-category-only", "name": "n", "category_origin": "small_implementation",
             "tags": ["unrelated-tag"]},
        ]}
        retro = {"metadata": {"category": "small_implementation", "project_name": "p"},
                 "lessons_learned": [lesson]}
        c = kc.generate_improvement_candidates(retro, reg)
        ids = {x["component_id"] for x in c}
        self.assertIn("skill-tag-match", ids)
        self.assertNotIn("skill-category-only", ids)

    def test_mixed_lessons_only_narrow_ones_are_restricted(self):
        """1 レトロに広い教訓と狭い教訓が混在しても、それぞれ独立に判定される。"""
        broad = {"priority": "medium", "lesson": "pytest で確かめる", "evidence": "",
                 "applicability": "all projects"}
        narrow = {"priority": "medium", "lesson": "自己変更固有の教訓", "evidence": "D-01",
                 "applicability": "self-modifying projects"}
        retro = {"metadata": {"category": "small_implementation", "project_name": "p"},
                 "lessons_learned": [broad, narrow]}
        c = kc.generate_improvement_candidates(retro, self._five_skills_same_category())
        # broad の教訓のみが5件マッチし、narrow はタグの重なりが無く0件 → 合計5件
        self.assertEqual(len(c), kc.MAX_CANDIDATES_PER_LESSON)


if __name__ == "__main__":
    unittest.main()
