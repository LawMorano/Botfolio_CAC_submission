# EmailJS production setup for Botfolio

The application sends these template parameters to EmailJS:

- `to_email`, `to_name`
- `from_name`, `from_email`, `reply_to`
- `subject`, `heading`, `message`
- `action_url`, `action_text`
- `greeting`, `intro`, `purpose`, `security_notice`, `signoff`
- `footer`, `website_url`
- `event_type`, `team_number`, `team_name`

## Service and sender

1. Do not use the current Gmail service for production account email.
2. In EmailJS, connect a transactional provider or mail service that has
   authenticated `botfoliohq.com`.
3. Verify `noreply@botfoliohq.com` with that provider.
4. Configure SPF, DKIM, and DMARC using the DNS values supplied by the provider.
5. Keep the sender fixed as `Botfolio <noreply@botfoliohq.com>`. Never use a
   visitor-supplied address as the From address; use it only as Reply-To.

Set these Railway variables:

```env
EMAILJS_SERVICE_ID=<new production service ID>
EMAILJS_TEMPLATE_ID=<production template ID>
EMAILJS_PUBLIC_KEY=<EmailJS public key>
EMAILJS_PRIVATE_KEY=<private key, if required by the account>
BOTFOLIO_FROM_NAME=Botfolio
BOTFOLIO_FROM_EMAIL=noreply@botfoliohq.com
```

## EmailJS template settings

Use these values in the template settings:

```text
To Email: {{to_email}}
To Name: {{to_name}}
From Name: {{from_name}}
From Email: noreply@botfoliohq.com
Reply-To: {{reply_to}}
Subject: {{subject}}
```

If EmailJS shows a **Use Default Email Address** checkbox, enable it only after
the connected production service's default address is the authenticated
`noreply@botfoliohq.com` sender. Otherwise leave it disabled and use the fixed
address above.

Do not set From Email to `{{reply_to}}` or an end user's address. That causes
sender-alignment and deliverability problems.

## Suggested HTML content

```html
<div style="margin:0;background:#f4f7fa;padding:32px 16px;font-family:Arial,sans-serif;color:#172033">
  <div style="max-width:600px;margin:auto;background:#ffffff;border:1px solid #dce3ea;border-radius:12px;padding:32px">
    <h1 style="margin:0 0 24px;font-size:26px;color:#16324f">{{heading}}</h1>
    {{#greeting}}
      <p>{{greeting}}</p>
      <p>{{intro}}</p>
      <p>{{purpose}}</p>
    {{/greeting}}
    {{^greeting}}
      <p style="white-space:pre-line">{{message}}</p>
    {{/greeting}}
    {{#action_url}}
      <p style="margin:28px 0;text-align:center">
        <a href="{{action_url}}" style="display:inline-block;background:#1e5a7a;color:#ffffff;text-decoration:none;font-weight:bold;padding:13px 22px;border-radius:8px">{{action_text}}</a>
      </p>
    {{/action_url}}
    {{#security_notice}}<p style="color:#526174">{{security_notice}}</p>{{/security_notice}}
    {{#signoff}}<p style="white-space:pre-line">{{signoff}}</p>{{/signoff}}
    <p><a href="{{website_url}}">botfoliohq.com</a></p>
    <hr style="border:0;border-top:1px solid #dce3ea;margin:28px 0 18px">
    <p style="font-size:12px;line-height:1.5;color:#6c7888">{{footer}}</p>
  </div>
</div>
```

The conditional blocks hide the button when `action_url` is empty and use the
generic `message` field for contact, moderation, and other non-verification
emails.

## Verification test

After deploying:

1. Register a new test account on `https://botfoliohq.com`.
2. Confirm the visible sender is `Botfolio <noreply@botfoliohq.com>`.
3. Confirm the subject is `Verify your Botfolio email`.
4. Confirm the verification button points to `https://botfoliohq.com/verify-email/...`.
5. Confirm the message reaches Gmail and Outlook without a spoofing warning.
6. Confirm SPF, DKIM, and DMARC pass in the received message headers.
7. Confirm the link works once and an expired/used link is rejected.
