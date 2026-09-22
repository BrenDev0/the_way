from dataclasses import dataclass


@dataclass
class Email:
    recipient: str
    subject: str
    html_body: str
