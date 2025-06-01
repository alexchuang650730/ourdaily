from typing import List, Dict, Tuple, Optional, Any
from rouge_score import rouge_scorer, scoring # Requires: pip install rouge-score nltk
import nltk # For tokenization if not already handled by rouge_scorer
import os
import json
import logging

from ..core.config import settings, PROJECT_ROOT_DIR # Adjusted import path

logger = logging.getLogger(__name__)

# NLTK resource management: It's good practice to check/download NLTK resources explicitly.
# This can be done once at application startup or module import.
_nltk_punkt_downloaded = False

def ensure_nltk_punkt():
    global _nltk_punkt_downloaded
    if _nltk_punkt_downloaded:
        return
    try:
        nltk.data.find("tokenizers/punkt")
        _nltk_punkt_downloaded = True
        logger.debug("NLTK punkt tokenizer found.")
    except LookupError:
        logger.info("NLTK punkt tokenizer not found. Attempting to download...")
        try:
            nltk.download("punkt", quiet=False) # Set quiet=False to see download progress/errors
            nltk.data.find("tokenizers/punkt") # Verify after download
            _nltk_punkt_downloaded = True
            logger.info("NLTK punkt tokenizer downloaded successfully.")
        except Exception as e_download:
            logger.error(f"Failed to download NLTK punkt tokenizer: {e_download}. ROUGE scores might be affected or inaccurate.", exc_info=True)
    except Exception as e_find:
        logger.error(f"Error checking for NLTK punkt tokenizer: {e_find}. ROUGE scores might be affected.", exc_info=True)

# Call it once when the module is loaded to ensure Punkt is ready.
ensure_nltk_punkt()

class ConfidenceResult:
    def __init__(self, score: float, keywords_found: List[str], needs_refinement: bool, details: Optional[Dict[str, Any]] = None):
        self.score = score # ROUGE-L F1 score
        self.keywords_found = keywords_found
        self.needs_refinement = needs_refinement
        self.details = details if details else {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rouge_l_f1_score": self.score,
            "keywords_found": self.keywords_found,
            "needs_refinement": self.needs_refinement,
            "details": self.details
        }
    
    def __repr__(self) -> str:
        return f"ConfidenceResult(score={self.score:.4f}, keywords={self.keywords_found}, needs_refinement={self.needs_refinement})"

class ConfidenceService:
    def __init__(self):
        self.rouge_threshold = settings.confidence.rouge_l_threshold
        self.keyword_triggers_file_name = settings.confidence.keyword_triggers_file
        self.keyword_triggers_file_path = os.path.join(PROJECT_ROOT_DIR, "config", self.keyword_triggers_file_name)
        self.keyword_triggers: List[str] = []
        self.scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
        logger.info(f"ConfidenceService initialized. ROUGE-L threshold: {self.rouge_threshold}, Keywords file: {self.keyword_triggers_file_path}")
        # Keywords are loaded asynchronously via load_keywords()

    async def load_keywords(self) -> None:
        """Loads keyword triggers from the specified JSON file. Should be called during app startup."""
        global _loaded_keyword_triggers # Using the global cache from config.py for consistency if desired
                                      # Or manage independently here.
                                      # For this service, let's use its own loaded list.
        
        keywords_list: List[str] = []
        try:
            if not os.path.exists(self.keyword_triggers_file_path):
                logger.warning(f"Keyword triggers file not found at {self.keyword_triggers_file_path}. Creating an empty one.")
                os.makedirs(os.path.dirname(self.keyword_triggers_file_path), exist_ok=True)
                with open(self.keyword_triggers_file_path, "w", encoding="utf-8") as f:
                    json.dump([], f)
                self.keyword_triggers = []
                return

            with open(self.keyword_triggers_file_path, "r", encoding="utf-8") as f:
                keywords_from_file = json.load(f)
                if isinstance(keywords_from_file, list) and all(isinstance(kw, str) for kw in keywords_from_file):
                    keywords_list = [kw.lower().strip() for kw in keywords_from_file if kw.strip()] # Lowercase and remove whitespace
                    self.keyword_triggers = keywords_list
                    logger.info(f"Successfully loaded and processed {len(self.keyword_triggers)} keyword triggers from {self.keyword_triggers_file_path}.")
                else:
                    logger.warning(f"Keyword triggers file {self.keyword_triggers_file_path} does not contain a list of strings. No keywords loaded.")
                    self.keyword_triggers = []
        except json.JSONDecodeError:
            logger.error(f"Error decoding JSON from keyword triggers file {self.keyword_triggers_file_path}. No keywords loaded.", exc_info=True)
            self.keyword_triggers = []
        except Exception as e:
            logger.error(f"An unexpected error occurred while loading keywords from {self.keyword_triggers_file_path}: {e}. No keywords loaded.", exc_info=True)
            self.keyword_triggers = []

    def _calculate_rouge_l(self, generated_text: str, reference_text: str) -> Tuple[float, Dict[str, scoring.Score]]:
        if not generated_text or not reference_text:
            logger.debug("ROUGE-L: Empty generated_text or reference_text, returning 0.0 score.")
            return 0.0, {}
        
        if not _nltk_punkt_downloaded:
            logger.warning("ROUGE-L: NLTK punkt tokenizer not available. ROUGE scores might be inaccurate.")
            # Scorer might still work with basic tokenization, but it's not ideal.

        try:
            # rouge_scorer expects prediction (generated) first, then target (reference)
            scores = self.scorer.score(prediction=generated_text, target=reference_text)
            rouge_l_score_obj = scores.get("rougeL")
            if rouge_l_score_obj:
                logger.debug(f"ROUGE-L scores: P={rouge_l_score_obj.precision:.4f}, R={rouge_l_score_obj.recall:.4f}, F1={rouge_l_score_obj.fmeasure:.4f}")
                return rouge_l_score_obj.fmeasure, scores
            logger.warning("ROUGE-L score object not found in scorer output.")
            return 0.0, scores
        except Exception as e:
            logger.error(f"Error during ROUGE-L calculation: {e}", exc_info=True)
            return 0.0, {}

    def _check_keywords(self, text_to_check: str) -> List[str]:
        if not text_to_check or not self.keyword_triggers:
            return []
        
        text_lower = text_to_check.lower()
        # Ensure keywords are pre-processed (e.g. lowercased, stripped) during load_keywords
        found_keywords = [kw for kw in self.keyword_triggers if kw in text_lower]
        if found_keywords:
            logger.debug(f"Keywords found in text: {found_keywords}")
        return found_keywords

    async def assess(self, generated_text: str, original_prompt: str) -> ConfidenceResult:
        if not self.keyword_triggers:
            # This check ensures that if load_keywords hasn't been called or failed,
            # we attempt it again. Ideally, load_keywords is called at startup.
            logger.info("Keywords not loaded in ConfidenceService instance, attempting to load now.")
            await self.load_keywords()

        keywords_found_in_prompt = self._check_keywords(original_prompt)
        rouge_l_f1, all_rouge_scores = self._calculate_rouge_l(generated_text=generated_text, reference_text=original_prompt)

        needs_refinement = False
        raw_scores_detail = {k: {"precision": v.precision, "recall": v.recall, "fmeasure": v.fmeasure} 
                             for k, v in all_rouge_scores.items()} if all_rouge_scores else {}
        assessment_details = {
            "rouge_l_f1_vs_prompt": rouge_l_f1,
            "keywords_in_prompt": keywords_found_in_prompt,
            "rouge_threshold_used": self.rouge_threshold,
            "raw_rouge_scores": raw_scores_detail
        }

        if keywords_found_in_prompt:
            needs_refinement = True
            assessment_details["reason_for_refinement"] = f"Keyword trigger(s) in prompt: {keywords_found_in_prompt}."
            logger.info(f"Confidence: Low (Keyword Trigger). Prompt: '{original_prompt[:50]}...', Keywords: {keywords_found_in_prompt}")
        elif rouge_l_f1 < self.rouge_threshold:
            needs_refinement = True
            assessment_details["reason_for_refinement"] = f"ROUGE-L F1 score ({rouge_l_f1:.4f}) below threshold ({self.rouge_threshold})."
            logger.info(f"Confidence: Low (ROUGE-L). Prompt: '{original_prompt[:50]}...', ROUGE-L: {rouge_l_f1:.4f}")
        else:
            assessment_details["reason_for_refinement"] = "High confidence (ROUGE-L above threshold and no keyword triggers)."
            logger.info(f"Confidence: High. Prompt: '{original_prompt[:50]}...', ROUGE-L: {rouge_l_f1:.4f}")
            
        return ConfidenceResult(
            score=rouge_l_f1,
            keywords_found=keywords_found_in_prompt,
            needs_refinement=needs_refinement,
            details=assessment_details
        )

