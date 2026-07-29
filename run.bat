MIT License

Copyright (c) 2026 AzurianNathan

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

This licence covers the code in THIS repository only: the local server, the
pure-JavaScript node router, the theme, the Optimize page and the patch scripts.

It does NOT cover the upstream projects this tool builds against, which are
fetched at build time and are not redistributed here:

  * shrddr/workermanjs  - https://github.com/shrddr/workermanjs
    No licence declared, so all rights are reserved by its author. This
    repository contains none of its source; build.py clones it directly from
    the author's repository onto your machine and applies patches locally.

  * Thell/bdo-empire    - https://github.com/Thell/bdo-empire
    Released under the Unlicense (public domain), installed from PyPI.
