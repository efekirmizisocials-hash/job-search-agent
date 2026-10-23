# Third-party software

The files below are vendored from [ai-job-search](https://github.com/ai-job-search-dev/ai-job-search), revision `e16acee3abdaae57f8026789338a3c6eebf4608b`:

- `vendor/posting_guard.py`
- `vendor/page_decode.py`
- `vendor/job_key.py`
- `vendor/portal_clis/{linkedin,freehire,jobnet,jobindex,jobbank,jobdanmark}`

The scoring rubric in `matcher.py` and document/form honesty guidance in
`documents.py` are adapted from upstream `04-job-evaluation.md` and
`08-application-forms.md` under the same license.

They are copyright © 2026 Mads Lorentzen and distributed under the MIT License:

The portal CLIs retain their upstream behavior. Small local additions expose a
raw `descriptionHtml` field for the posting-integrity guard; the original
plain-text `description` fields remain available to CLI consumers.

> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

Each portal talks to an independent hosted service. Use remains subject to that
service's terms. In particular, the LinkedIn CLI's upstream documentation marks
it for low-volume personal use and notes that automated access conflicts with
LinkedIn's terms of service.

## Public API references

The native adapters were implemented against the providers' published API
documentation, checked on 2026-10-23:

- [Remotive Remote Jobs API](https://github.com/remotive-com/remote-jobs-api)
- [Arbeitnow Job Board API](https://www.arbeitnow.com/blog/job-board-api)
- [Remote OK feeds](https://remoteok.com/faq)
- [Himalayas Remote Jobs API](https://himalayas.app/docs/remote-jobs-api)
- [Adzuna API](https://developer.adzuna.com/overview)
- [Jooble REST API](https://jooblehelpcenter.freshdesk.com/en/support/solutions/articles/60001448238-rest-api-documentation)
- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board)
- [Lever Postings API](https://github.com/lever/postings-api)
- [Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api)
