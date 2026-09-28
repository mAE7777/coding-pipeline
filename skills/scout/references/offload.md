# The ChatGPT offload prompt

Fill the brackets and give the whole block to the owner to paste into ChatGPT (a model with web search).

    I need research that will decide a real choice, and I will check your sources, so accuracy matters more
    than coverage.

    Decision: <the decision this serves>
    The assumption that would kill the leading option: <the assumption>
    Question: <the question, precisely>
    Claims to check (confirm, correct, or refute each): <numbered claims, or "none">

    Rules:
    1. Search the web. For every claim, cite the page (URL) and the date you read it. Prefer the maker's own
       documentation, pricing or limits page, source code, release notes, or filing over articles about them.
    2. Two articles repeating one press release count as one source; say so.
    3. Search deliberately for evidence against your leading answer and report what you found.
    4. Put contested points first, with both sides.
    5. Grade each claim: primary, triangulated, single-source, inferred, or contested.
    6. If you cannot browse, say so at the top and grade everything as inferred.

    Output: one Markdown document, in this order: a two-to-five sentence answer; a table of claims (claim,
    grade, source URL, date read); what you searched against the answer and what it showed; open questions.
    I will save it as <absolute path>/docs/project/research/<slug>.chatgpt.md.

After the owner saves the answer there, run `/scout ingest docs/project/research/<slug>.chatgpt.md`.
