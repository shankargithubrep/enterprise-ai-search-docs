## What does this PR do?

<!-- One line summary: e.g. "Add SharePoint connector doc" or "Update S3 limitations table" -->

---

## Connector / Topic

<!-- Which connector or doc is this for? -->
- [ ] S3
- [ ] SharePoint Online
- [ ] Salesforce
- [ ] ServiceNow
- [ ] Confluence
- [ ] Web Crawler (Elastic)
- [ ] Custom Web Crawler
- [ ] Chunking Strategies
- [ ] README / repo structure
- [ ] Workflow / CI

---

## Checklist

### Content
- [ ] **Overview** section explains what the connector does and its role in the Enterprise AI-KB architecture
- [ ] **How It Works** covers the sync pipeline internals (not just surface-level description)
- [ ] **When to Use / When Not to Use** decision table is complete with verdicts and reasons
- [ ] **Configuration Reference** table covers all parameters with types, defaults, and deployment-specific notes
- [ ] **Known Limitations** table has severity ratings and mitigations for every item
- [ ] **Enterprise AI-KB Deployment Notes** section exists with deployment-specific guidance
- [ ] **Technical Q&A** has at least 6 questions covering internals, edge cases, and failure modes

### Code & Formatting
- [ ] All code blocks have a language identifier (` ```json `, ` ```python `, ` ```http `, etc.)
- [ ] IAM policies / config examples are valid JSON (validated locally)
- [ ] Python snippets are syntactically correct
- [ ] No marketing language — this is engineering documentation
- [ ] All internal anchor links (`[Section](#section)`) work locally (preview in VS Code or similar)

### Accuracy
- [ ] Connector version / ES version is specified
- [ ] Any known limitations are from actual connector behaviour, not assumptions
- [ ] deployment-specific details (tenant counts, instance types, prefix structure) match the current spec
- [ ] No placeholder `[SA to fill]` text left in merged content

---

## Testing

<!-- How did you verify the content? e.g. "Tested against Elastic 8.14 dev cluster", "Verified IAM policy in AWS console", "Validated JSON in jq" -->

---

## Related issues / refs

<!-- Link any relevant Elastic docs, GitHub issues, or internal spec docs -->
