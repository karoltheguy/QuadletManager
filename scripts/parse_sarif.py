import json
import os

sarif_file = 'codacy_results.sarif'
if not os.path.exists(sarif_file):
    print(f"Error: {sarif_file} not found.")
    exit(1)

with open(sarif_file) as f:
    data = json.load(f)

runs = data.get('runs', [])
total_results = 0
files = {}
rules = {}

for run in runs:
    results = run.get('results', [])
    total_results += len(results)
    for res in results:
        rule_id = res.get('ruleId', 'unknown')
        rules[rule_id] = rules.get(rule_id, 0) + 1
        locations = res.get('locations', [])
        if locations:
            uri = locations[0].get('physicalLocation', {}).get('artifactLocation', {}).get('uri', 'unknown')
            files[uri] = files.get(uri, 0) + 1

print(f'Total results: {total_results}')
print('\nResults by File:')
for k, v in sorted(files.items(), key=lambda x: x[1], reverse=True)[:15]:
    print(f'  {k}: {v}')
print('\nResults by Rule:')
for k, v in sorted(rules.items(), key=lambda x: x[1], reverse=True)[:15]:
    print(f'  {k}: {v}')
