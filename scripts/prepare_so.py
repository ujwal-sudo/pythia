import json
import os
import hashlib
import re
import requests
from scripts.validators.ast_validator import validate_python
import pycodestyle

from config import FILTERED_DIR, STAGE2_DIR

BASE_URL = "https://api.stackexchange.com/2.3"

def main():
    # Get Python questions with min score 10
    params = {'site': 'stackoverflow', 'tagged': 'python', 'min': '10', 'pagesize': '5'}
    r = requests.get(f'{BASE_URL}/questions', params=params, timeout=30)
    
    if r.status_code != 200:
        print(f'API error: status {r.status_code}')
        return
    
    data = r.json()
    print('Total questions:', data.get('total', 0))
    items = data.get('items', [])
    print('Got', len(items), 'questions')
    
    all_records = []
    seen_hashes = set()
    syntax_valid_count = 0
    syntax_invalid_count = 0
    below_comment_count = 0
    pep8_violation_counts = []
    exact_duplicates_count = 0
    
    for i, q in enumerate(items):
        if i >= 20:  # limit to 20 for now
            break
        
        qid = q['question_id']
        title = q.get('title', '')[:100]
        
        # Get answers
        ans_params = {'question': qid, 'site': 'stackoverflow', 'filter': '!9.ZnKeNJl4g61fHiV'}
        ans_r = requests.get(f'{BASE_URL}/questions/{qid}/answers', params=ans_params, timeout=30)
        
        if ans_r.status_code != 200:
            print(f'  Q {qid}: answers API error {ans_r.status_code}')
            continue
        
        ans_data = ans_r.json()
        answers = ans_data.get('items', [])
        
        # Find accepted answer
        accepted_answer = None
        for a in answers:
            if a.get('is_accepted'):
                accepted_answer = a
                break
        
        if accepted_answer is None:
            print(f'  Q {qid}: no accepted answer')
            continue
        
        answer_id = accepted_answer.get('answer_id', '')
        answer_body = accepted_answer.get('body', '')
        
        # Extract Python code from answer body
        code_text = re.sub(r'<[^>]+>', '\n', answer_body)
        
        # Simple heuristic: check for Python indicators
        python_keywords = ['def ', 'import ', 'class ', 'print(', 'range(', 'if ', 'for ', 'while ', 'return ']
        code_lower = code_text.lower()
        is_python = any(kw in code_lower for kw in python_keywords)
        
        if not is_python:
            print(f'  Q {qid}: not Python-like')
            continue
        
        # AST validation
        validation = validate_python(code_text)
        syntax_valid = validation.is_valid
        
        if syntax_valid:
            syntax_valid_count += 1
        else:
            syntax_invalid_count += 1
        
        # Provisional token count
        char_count = len(code_text)
        provisional_token_count = max(1, char_count // 4)
        
        # Comment/docstring ratio from validator
        comment_ratio = validation.comment_ratio
        
        # PEP8 violations
        pep8_violations = 0
        try:
            old_stdout = __import__('sys').stdout
            __import__('sys').stdout = __import__('io').StringIO()
            try:
                runner = pycodestyle.api.Checker(code_text.split('\n'), format='total')
                pep8_violations = runner.total_errors
            except Exception:
                pep8_violations = 0
            finally:
                __import__('sys').stdout = old_stdout
        except Exception:
            pep8_violations = 0
        
        pep8_violation_counts.append(pep8_violations)
        
        # SHA-256 hash
        code_hash = hashlib.sha256(code_text.encode("utf-8")).hexdigest()
        
        # Duplicate check
        near_duplicate_status = 'pending'
        if code_hash in seen_hashes:
            near_duplicate_status = 'exact_duplicate'
            exact_duplicates_count += 1
        seen_hashes.add(code_hash)
        
        # Build record
        record = {
            'id': f'so_{qid}_{answer_id}',
            'code': code_text,
            'context': f'stackoverflow question {qid}',
            'source': 'stackoverflow',
            'stage': 2,
            'source_url': q.get('link', ''),
            'repository': None,
            'file_path': '',
            'commit_id': '',
            'license': 'CC BY-SA 4.0',
            'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/',
            'retrieved_at': '2026-09-15',
            'provisional_token_count': provisional_token_count,
            'comment_ratio': round(comment_ratio, 4),
            'pep8_violations': pep8_violations,
            'syntax_prevalidated': syntax_valid,
            'authoritative_validator_status': 'completed' if syntax_valid else 'failed',
            'kg_validation_status': 'pending',
            'exact_hash': code_hash,
            'near_duplicate_status': near_duplicate_status
        }
        
        all_records.append(record)
        
        if (i + 1) % 5 == 0:
            print(f'  Processed {i+1}/{len(items)} questions')
    
    print(f'\\nStack Overflow records: {len(all_records)}')
    print(f'  Syntax-valid: {syntax_valid_count}')
    print(f'  Syntax-invalid: {syntax_invalid_count}')
    print(f'  Below comment threshold (<0.1): {below_comment_count if "below_comment_count" in dir() else "N/A"}')
    print(f'  Exact duplicates: {exact_duplicates_count}')
    
    # Write output
    output_path = STAGE2_DIR / "stackoverflow_candidates.jsonl"
    os.makedirs(output_path.parent, exist_ok=True)
    with open(output_path, 'w') as f:
        for rec in all_records:
            f.write(json.dumps(rec) + '\n')
    
    print(f'\\nOutput: {output_path}')

if __name__ == '__main__':
    main()