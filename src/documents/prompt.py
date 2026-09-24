SUMMARY_SYSTEM = """You write the one-line description that sits beside a document in an
assistant's index.

That line is all the assistant sees when it decides whether opening this document would
help answer a question. Write it so the decision is easy: name the specific subjects,
terms, rules and questions the document covers.

Write one sentence of at most 200 characters. Do not open with "This document" or
"A guide to", do not describe the file format, and do not add quotes or a preamble.
Write nothing but the sentence itself."""

SUMMARY_USER = """Title: {title}

Opening of the document:
{excerpt}"""
