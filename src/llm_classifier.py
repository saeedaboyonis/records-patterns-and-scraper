"""
LLM-based Document Type Classifier - Bonus Task

This module uses a LOCAL LLM via Ollama to classify messy document types
into standardized categories. No API keys, no billing, fully free.

Target Categories:
- SALE_DEED
- MORTGAGE
- DEED_OF_TRUST
- RELEASE
- LIEN
- PLAT
- EASEMENT
- LEASE
- MISC

Features:
- Strategic sampling (frequent + rare types)
- Local LLM via Ollama (free, no API keys)
- Dry-run mode (rule-based, no LLM calls)
- Confidence scoring
- Uncertain mapping flagging

Setup:
    1. Install Ollama: https://ollama.ai/download
    2. Pull the model: ollama pull llama3.1:8b
    3. Run Ollama server (usually auto-starts)

Usage:
    # With local Ollama LLM
    python -m src.llm_classifier --input file.jsonl --output outputs/doc_type_mapping.json
    
    # Dry-run mode (no LLM needed)
    python -m src.llm_classifier --input file.jsonl --dry-run
    
    # Use different model
    python -m src.llm_classifier --input file.jsonl --model llama3.1:8b
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import os

from .domain.models import (
    DocTypeMapping,
    ClassificationResult,
)
from .io.jsonl_reader import JsonlReader
from .io.json_writer import JsonWriter
from .infra.logging import setup_logging, get_logger


logger = get_logger(__name__)


# Standard categories
STANDARD_CATEGORIES = [
    "SALE_DEED",
    "MORTGAGE",
    "DEED_OF_TRUST",
    "RELEASE",
    "LIEN",
    "PLAT",
    "EASEMENT",
    "LEASE",
    "MISC",
]

# Default Ollama model
DEFAULT_MODEL = "llama3.1:8b"


@dataclass
class TokenUsage:
    """Track token usage for reporting (not available with Ollama)."""
    input_tokens: int = 0
    output_tokens: int = 0
    
    def add(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
    
    def estimate_cost(self, model: str = DEFAULT_MODEL) -> float:
        """Local LLM has no cost."""
        return 0.0


def extract_json_from_response(text: str) -> Any:
    """
    Extract JSON from potentially messy LLM response.
    
    Handles cases where the model returns extra text around the JSON.
    
    Args:
        text: Raw response text from the model
        
    Returns:
        Parsed JSON object/array
        
    Raises:
        ValueError: If no valid JSON can be extracted
    """
    text = text.strip()
    
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON array
    array_match = re.search(r'\[[\s\S]*\]', text)
    if array_match:
        try:
            return json.loads(array_match.group())
        except json.JSONDecodeError:
            pass
    
    # Try to find JSON object
    object_match = re.search(r'\{[\s\S]*\}', text)
    if object_match:
        try:
            return json.loads(object_match.group())
        except json.JSONDecodeError:
            pass
    
    # Try removing markdown code blocks
    cleaned = re.sub(r'```(?:json)?\s*', '', text)
    cleaned = re.sub(r'```\s*$', '', cleaned)
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        pass
    
    raise ValueError(f"Could not extract valid JSON from response: {text[:200]}...")


class DocTypeSampler:
    """
    Strategically samples document types for LLM classification.
    
    Sampling strategy:
    1. All unique doc_types
    2. Prioritize by frequency for validation
    3. Include rare types that might be unusual
    """
    
    def __init__(self, min_frequency: int = 1):
        """
        Initialize the sampler.
        
        Args:
            min_frequency: Minimum frequency to include a doc_type
        """
        self.min_frequency = min_frequency
        self.doc_type_counts: Counter = Counter()

    def collect_from_reader(self, reader: JsonlReader) -> None:
        """
        Collect document type frequencies from a JSONL reader.
        
        Args:
            reader: JsonlReader instance
        """
        logger.info("Collecting document type frequencies...")
        
        for record in reader:
            doc_type = record.get("doc_type")
            if doc_type:
                self.doc_type_counts[str(doc_type).strip()] += 1
        
        logger.info(f"Found {len(self.doc_type_counts)} unique doc_types")

    def get_sample(
        self,
        max_types: Optional[int] = None,
        include_rare: bool = True,
    ) -> list[tuple[str, int]]:
        """
        Get a strategic sample of document types.
        
        Args:
            max_types: Maximum number of types to return
            include_rare: Whether to include rare types
            
        Returns:
            List of (doc_type, frequency) tuples
        """
        # Filter by minimum frequency
        filtered = [
            (dt, count) for dt, count in self.doc_type_counts.items()
            if count >= self.min_frequency
        ]
        
        # Sort by frequency (descending)
        sorted_types = sorted(filtered, key=lambda x: -x[1])
        
        if max_types and len(sorted_types) > max_types:
            # Take top frequent types
            frequent = sorted_types[:max_types // 2]
            
            # Take some rare types if requested
            if include_rare:
                rare_count = max_types - len(frequent)
                rare = sorted_types[-(rare_count):]
                return frequent + rare
            
            return sorted_types[:max_types]
        
        return sorted_types

    def get_total_records(self) -> int:
        """Get total record count."""
        return sum(self.doc_type_counts.values())

    def get_unique_count(self) -> int:
        """Get unique doc_type count."""
        return len(self.doc_type_counts)


class OllamaMapper:
    """
    Maps document types to standard categories using local Ollama LLM.
    
    This class uses Ollama with a local model (default: llama3.1:8b) to classify
    document types into standardized categories with confidence scoring.
    
    Benefits:
    - Completely free (no API costs)
    - No rate limits or quotas
    - Works offline
    - Data stays local
    """
    
    SYSTEM_PROMPT = """You are an expert in real estate and property records documentation.
Your task is to classify document types from property records into standardized categories.

Standard Categories:
- SALE_DEED: Documents transferring property ownership (warranty deed, quitclaim deed, deed, grant deed)
- MORTGAGE: Documents securing a loan with property (mortgage)
- DEED_OF_TRUST: Trust-based security instruments (deed of trust, trust deed, assignment of deed of trust)
- RELEASE: Documents releasing liens, mortgages, or claims (satisfaction, release, discharge, cancellation)
- LIEN: Documents creating claims against property (lis pendens, mechanic's lien, tax lien, judgment lien)
- PLAT: Maps and surveys of property (plat, subdivision, survey, map)
- EASEMENT: Rights to use another's property (easement, right of way, utility easement)
- LEASE: Rental/lease agreements (lease, ground lease, rental agreement)
- MISC: Any document that doesn't clearly fit the above categories

EXAMPLES:
- "DEED" => SALE_DEED (basic deed for property transfer)
- "WARRANTY DEED" => SALE_DEED (deed with title warranty)
- "QUITCLAIM DEED" => SALE_DEED (deed releasing interest)
- "MORTGAGE" => MORTGAGE (loan secured by property)
- "DEED OF TRUST" => DEED_OF_TRUST (trust-based security)
- "DT" => DEED_OF_TRUST (abbreviation for deed of trust)
- "D T" => DEED_OF_TRUST (abbreviation with space)
- "ASSIGNMENT OF DEED OF TRUST" => DEED_OF_TRUST (transfer of trust)
- "SATISFACTION" => RELEASE (debt paid off)
- "RELEASE" => RELEASE (releasing a claim)
- "CANCELLATION" => RELEASE (canceling a lien/mortgage)
- "LIEN" => LIEN (claim against property)
- "LIS PENDENS" => LIEN (pending litigation notice)
- "PLAT" => PLAT (property map)
- "MAP" => PLAT (survey map)
- "EASEMENT" => EASEMENT (right to use property)
- "RIGHT OF WAY" => EASEMENT (passage right)
- "LEASE" => LEASE (rental agreement)

CRITICAL INSTRUCTIONS:
1. Respond with ONLY a valid JSON array - no markdown, no explanation, no extra text
2. Each item must have exactly these fields: original_type, category, confidence, reasoning
3. category must be exactly one of: SALE_DEED, MORTGAGE, DEED_OF_TRUST, RELEASE, LIEN, PLAT, EASEMENT, LEASE, MISC
4. confidence must be a number between 0.0 and 1.0
5. reasoning should be brief (under 50 characters)"""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        batch_size: int = 20,
    ):
        """
        Initialize the Ollama mapper.
        
        Args:
            model: Ollama model to use for classification
            batch_size: Number of doc_types to classify per LLM call
        """
        self.model = model
        self.batch_size = batch_size
        self.token_usage = TokenUsage()
        
        self._client = None
        self._available = False
        
        # Get Ollama host from environment (for Docker Compose support)
        self._host = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        
        try:
            import ollama
            # Create client with configurable host
            self._client = ollama.Client(host=self._host)
            # Test if Ollama is running and model is available
            try:
                # Quick check - list models
                models = self._client.list()
                model_names = [m.get('name', m.get('model', '')) for m in models.get('models', [])]
                # Check if our model is available (handle both "llama3.1:8b" and "llama3.1:8b-instruct-..." formats)
                base_model = model.split(':')[0]
                self._available = any(base_model in name for name in model_names)
                if not self._available:
                    logger.warning(f"Model '{model}' not found. Available models: {model_names}")
                    logger.warning(f"Pull the model with: ollama pull {model}")
            except Exception as e:
                logger.warning(f"Ollama server not responding at {self._host}: {e}")
                logger.warning("Make sure Ollama is installed and running: https://ollama.ai/download")
                logger.warning("For Docker: docker compose up -d ollama && ./scripts/pull_ollama_model.sh")
        except ImportError:
            logger.warning("ollama package not installed. Install with: pip install ollama")

    @property
    def is_available(self) -> bool:
        """Check if the Ollama client is available."""
        return self._client is not None and self._available

    def classify_batch(
        self,
        doc_types: list[tuple[str, int]],
    ) -> list[DocTypeMapping]:
        """
        Classify a batch of document types.
        
        Args:
            doc_types: List of (doc_type, frequency) tuples
            
        Returns:
            List of DocTypeMapping objects
        """
        if not self.is_available:
            raise RuntimeError("Ollama client not available")
        
        # Build prompt
        doc_type_list = "\n".join([
            f"- {dt} (frequency: {freq})"
            for dt, freq in doc_types
        ])
        
        user_prompt = f"""Classify the following document types into standard categories.

{doc_type_list}

Respond with a JSON array only. Example format:
[
    {{"original_type": "WARRANTY DEED", "category": "SALE_DEED", "confidence": 0.95, "reasoning": "Deed for property transfer"}},
    {{"original_type": "DT", "category": "DEED_OF_TRUST", "confidence": 0.9, "reasoning": "Abbreviation for deed of trust"}}
]

JSON array:"""

        try:
            # Call Ollama using the configured client
            response = self._client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                options={
                    "temperature": 0,  # Deterministic for consistency
                },
            )
            
            # Parse response
            content = response.get('message', {}).get('content', '')
            result = extract_json_from_response(content)
            
            # Handle both array and object responses
            if isinstance(result, dict):
                result = result.get("classifications", result.get("mappings", [result]))
            
            # Convert to DocTypeMapping objects
            mappings = []
            freq_map = {dt: freq for dt, freq in doc_types}
            
            for item in result:
                original_type = item.get("original_type", "")
                category = item.get("category", "MISC")
                confidence = float(item.get("confidence", 0.5))
                reasoning = item.get("reasoning", "")[:100]  # Truncate long reasoning
                
                # Validate category
                if category not in STANDARD_CATEGORIES:
                    logger.warning(f"Invalid category '{category}' for '{original_type}', defaulting to MISC")
                    category = "MISC"
                    confidence = min(confidence, 0.5)
                
                mappings.append(DocTypeMapping(
                    original_type=original_type,
                    standard_category=category,
                    confidence=confidence,
                    frequency=freq_map.get(original_type, 0),
                    is_uncertain=confidence < 0.7,
                    reasoning=reasoning,
                ))
            
            return mappings
            
        except Exception as e:
            logger.error(f"Ollama classification failed: {e}")
            raise

    def classify_all(
        self,
        doc_types: list[tuple[str, int]],
    ) -> list[DocTypeMapping]:
        """
        Classify all document types in batches.
        
        Args:
            doc_types: List of (doc_type, frequency) tuples
            
        Returns:
            List of all DocTypeMapping objects
        """
        all_mappings = []
        total_batches = (len(doc_types) + self.batch_size - 1) // self.batch_size
        
        for i in range(0, len(doc_types), self.batch_size):
            batch = doc_types[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} types)")
            
            mappings = self.classify_batch(batch)
            all_mappings.extend(mappings)
        
        return all_mappings


class RuleBasedMapper:
    """
    Rule-based document type mapper for dry-run mode.
    
    Uses keyword matching to classify document types without LLM.
    Priority ordering matters - more specific patterns are checked first.
    """
    
    RULES = [
        # DEED_OF_TRUST - must be checked BEFORE SALE_DEED (contains "deed")
        # Includes abbreviations: DT, D T, D-TR, D OF T, DOT, TRS D, SUB TR, D/T, PRE D/T, SUB-T
        (r"deed of trust|trust deed|d\.?o\.?t\.?\b|d\s*t\b|d-tr|d of t|deed-of-trust|dot\b|trs\s*d\b|sub\s*tr\b|d/t|pre\s*d/t|sub-t", "DEED_OF_TRUST", 0.9),
        # MORTGAGE - includes MTGE, MTG abbreviations
        (r"mortgage|mtg\b|mtge\b|mod\b.*mortgage|modification.*mortgage", "MORTGAGE", 0.9),
        # RELEASE - check before deeds since "rel deed" is a release, includes D & REL
        (r"^rel\b|release|satisfaction|discharge|reconveyance|cancellation|\bsat\b|\bcan\b|partial rel|d\s*&\s*rel", "RELEASE", 0.85),
        # SALE_DEED - various deed types including QCD, Q C D, CORR D, CONDO, TIM D, CONT CONVY, CMS D
        (r"deed(?! of trust)|warranty|quitclaim|quit claim|qcd\b|q\s*c\s*d\b|grant deed|bargain|conveyance|convy|special warranty|general warranty|executor.*deed|fiduciary|administrator.*deed|guardian.*deed|commissioner.*deed|trustee.*deed|sherif.*deed|tax deed|court order.*deed|ref deed|correction deed|corr\s*d\b|condo|tim\s*d\b|cms\s*d\b", "SALE_DEED", 0.85),
        # LIEN - includes FC (foreclosure), UCC, F S (financing statement)
        (r"lien|lis pendens|judgment|levy|attachment|notice of default|notice of trustee|mechanics.*lien|materialman|federal tax|state tax|claim of lien|\bfc\b|uniform commercial code|\bucc\b|f\s*s\b", "LIEN", 0.8),
        # PLAT - include map revisions, SUB D (subdivision), dedication, DE (dedication)
        (r"plat|subdivision|survey|map|replat|boundary|rev.*map|map.*rev|/r\b|\bsub\s*d\b|dedication|\bde\b|decla.*condo", "PLAT", 0.9),
        # EASEMENT - includes ESMT, EASE, R-WAY, RW (right of way) abbreviations
        (r"easement|esmt\b|ease\b|right of way|r-way|r/w|\brw\b|utility.*easement|road.*easement|drainage.*easement|access.*easement", "EASEMENT", 0.85),
        # LEASE
        (r"lease|rental|ground lease|memorandum of lease|leasehold", "LEASE", 0.85),
        # ASSIGNMENT - typically goes with mortgages or deeds of trust (ASGMT, ASGN, ASIGN)
        (r"assignment\b|asgn\b|asgmt\b|asign\b|assign", "MORTGAGE", 0.7),
        # SUBSTITUTION OF TRUSTEE - related to deeds of trust
        (r"substitution.*trustee|sub.*trustee|appointment.*trustee", "DEED_OF_TRUST", 0.75),
        # FORECLOSURE - related to liens/enforcement
        (r"foreclosure|notice of sale|trustee sale|auction", "LIEN", 0.75),
        # UCC filings - typically liens
        (r"financing statement|fixture filing|security agreement", "LIEN", 0.8),
        # Common MISC categories - POA (PA, P A), affidavits, agreements, etc.
        (r"power of attorney|poa\b|\bpa\b|p\s*a\b|affidavit|afdvt\b|agreement\b|agmt\b|contract|covenant|cov\b|restrictive|restriction|restr|rest\b|declaration|resolution|certificate|consent|waiver|amendment|revocation|estoppel|subordination|modification|modif|assumed name|a\s*name\b|memo\b|memorandum|notice\b|request|req\b|r for n|supplement|historical|miscellaneous|see instrument|order\b|ordinance|articles|incorporation|\br\b", "MISC", 0.7),
    ]

    def classify(
        self,
        doc_types: list[tuple[str, int]],
    ) -> list[DocTypeMapping]:
        """
        Classify document types using rules.
        
        Args:
            doc_types: List of (doc_type, frequency) tuples
            
        Returns:
            List of DocTypeMapping objects
        """
        mappings = []
        
        for doc_type, frequency in doc_types:
            doc_type_lower = doc_type.lower()
            matched = False
            
            for pattern, category, confidence in self.RULES:
                if re.search(pattern, doc_type_lower, re.IGNORECASE):
                    mappings.append(DocTypeMapping(
                        original_type=doc_type,
                        standard_category=category,
                        confidence=confidence,
                        frequency=frequency,
                        is_uncertain=confidence < 0.7,
                        reasoning=f"Matched rule pattern: {pattern}",
                    ))
                    matched = True
                    break
            
            if not matched:
                mappings.append(DocTypeMapping(
                    original_type=doc_type,
                    standard_category="MISC",
                    confidence=0.5,
                    frequency=frequency,
                    is_uncertain=True,
                    reasoning="No matching rule found",
                ))
        
        return mappings


class LLMClassifier:
    """
    Main classifier that orchestrates the classification process.
    
    This class coordinates:
    - Sampling document types
    - Local Ollama LLM or rule-based classification
    - Result aggregation
    - Output generation
    """
    
    def __init__(
        self,
        input_path: str,
        output_path: str,
        model: str = DEFAULT_MODEL,
        batch_size: int = 20,
        dry_run: bool = False,
        max_types: Optional[int] = None,
    ):
        """
        Initialize the classifier.
        
        Args:
            input_path: Path to input JSONL file
            output_path: Path for output JSON file
            model: Ollama model to use
            batch_size: Number of types per batch
            dry_run: If True, use rule-based classification
            max_types: Maximum types to classify
        """
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.model = model
        self.batch_size = batch_size
        self.dry_run = dry_run
        self.max_types = max_types

    def classify(self) -> ClassificationResult:
        """
        Run the classification process.
        
        Returns:
            ClassificationResult with all mappings
            
        Raises:
            RuntimeError: If Ollama is not available and not in dry-run mode
        """
        logger.info(f"Starting classification from: {self.input_path}")
        
        # Sample document types
        sampler = DocTypeSampler()
        reader = JsonlReader(self.input_path, skip_errors=True)
        sampler.collect_from_reader(reader)
        
        doc_types = sampler.get_sample(max_types=self.max_types)
        logger.info(f"Sampled {len(doc_types)} document types for classification")
        
        # Classify
        if self.dry_run:
            logger.info("Running in dry-run mode (rule-based classification)")
            mapper = RuleBasedMapper()
            mappings = mapper.classify(doc_types)
            token_usage = TokenUsage()
            api_calls = 0
        else:
            logger.info(f"Using local Ollama LLM with model: {self.model}")
            mapper = OllamaMapper(model=self.model, batch_size=self.batch_size)
            
            if not mapper.is_available:
                raise RuntimeError(
                    f"Ollama not available. Please ensure:\n"
                    f"  1. Ollama is installed: https://ollama.ai/download\n"
                    f"  2. Ollama server is running\n"
                    f"  3. Model is pulled: ollama pull {self.model}\n"
                    f"  4. Python package is installed: pip install ollama\n"
                    f"\nAlternatively, run with --dry-run for rule-based classification."
                )
            
            mappings = mapper.classify_all(doc_types)
            token_usage = mapper.token_usage
            api_calls = (len(doc_types) + mapper.batch_size - 1) // mapper.batch_size
        
        # Build result
        uncertain_count = sum(1 for m in mappings if m.is_uncertain)
        total_records = sum(m.frequency for m in mappings)
        
        result = ClassificationResult(
            mappings=sorted(mappings, key=lambda m: -m.frequency),
            total_types_processed=len(mappings),
            total_records_covered=total_records,
            uncertain_mappings=uncertain_count,
            api_calls_made=api_calls,
            total_tokens_used=token_usage.input_tokens + token_usage.output_tokens,
            estimated_cost=token_usage.estimate_cost(self.model),
            dry_run=self.dry_run,
        )
        
        # Write outputs:
        # 1. Main output: simple mapping dictionary (per PDF spec)
        logger.info(f"Writing mapping dictionary to: {self.output_path}")
        mapping_dict = {m.original_type: m.standard_category for m in result.mappings}
        writer = JsonWriter(self.output_path)
        writer.write(mapping_dict)
        
        # 2. Details file: full report with confidence, reasoning, etc.
        output_str = str(self.output_path)
        if output_str.endswith(".json"):
            details_path = output_str[:-5] + "_details.json"
        else:
            details_path = output_str + "_details.json"
        logger.info(f"Writing detailed report to: {details_path}")
        details_writer = JsonWriter(details_path)
        details_writer.write(result.to_dict())
        
        return result


def main():
    """Main entry point for the LLM classifier CLI."""
    parser = argparse.ArgumentParser(
        description="Classify document types using local Ollama LLM (free, no API keys)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # First, pull the model
  ollama pull llama3.1:8b
  
  # Run classification
  python -m src.llm_classifier --input records.jsonl --output mappings.json
  
  # Use specific model
  python -m src.llm_classifier --input records.jsonl --model llama3.1:8b
  
  # Dry-run mode (no LLM needed)
  python -m src.llm_classifier --input records.jsonl --dry-run
  
  # Limit types to classify
  python -m src.llm_classifier --input records.jsonl --max-types 100

Requirements:
  1. Install Ollama: https://ollama.ai/download
  2. Pull a model: ollama pull llama3.1:8b
  3. Install Python package: pip install ollama
        """
    )
    
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to input JSONL file"
    )
    
    parser.add_argument(
        "--output", "-o",
        default="outputs/doc_type_mapping.json",
        help="Path for output JSON file"
    )
    
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model to use (default: {DEFAULT_MODEL})"
    )
    
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Number of doc_types per batch (default: 20)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use rule-based classification instead of LLM"
    )
    
    parser.add_argument(
        "--max-types",
        type=int,
        help="Maximum number of doc_types to classify"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    import logging
    log_level = getattr(logging, args.log_level)
    setup_logging(level=log_level)
    
    # Validate input
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)
    
    # Run classification
    try:
        classifier = LLMClassifier(
            input_path=str(input_path),
            output_path=args.output,
            model=args.model,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            max_types=args.max_types,
        )
        
        result = classifier.classify()
        
        # Print summary
        print(f"\n{'='*60}")
        print("CLASSIFICATION SUMMARY")
        print(f"{'='*60}")
        print(f"Types processed: {result.total_types_processed}")
        print(f"Records covered: {result.total_records_covered:,}")
        print(f"Uncertain mappings: {result.uncertain_mappings}")
        print(f"LLM calls made: {result.api_calls_made}")
        print(f"Total tokens used: N/A (local LLM)")
        print(f"Estimated cost: $0.00 (local LLM - free)")
        print(f"Dry run: {result.dry_run}")
        
        # Show category distribution
        category_counts = Counter()
        for mapping in result.mappings:
            category_counts[mapping.standard_category] += mapping.frequency
        
        print(f"\nCategory Distribution:")
        for category, count in category_counts.most_common():
            pct = count / result.total_records_covered * 100 if result.total_records_covered > 0 else 0
            print(f"  {category}: {count:,} ({pct:.1f}%)")
        
        print(f"\nResults written to: {args.output}")
        
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Classification failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
