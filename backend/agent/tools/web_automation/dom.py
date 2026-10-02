"""DOM inspection, interactive element extraction, and HTML simplification."""
from __future__ import annotations
import re
from typing import Any
from backend.agent.tools.web_automation.models import InteractiveElement

# Comprehensive JavaScript snippet to extract live interactive elements from the DOM
DOM_EXTRACTION_SCRIPT = """(() => {
    function getCssSelector(el) {
        if (!el || el.nodeType !== Node.ELEMENT_NODE) return '';
        if (el.id && !/^[0-9]/.test(el.id) && !el.id.includes(' ')) {
            return '#' + CSS.escape(el.id);
        }
        if (el.name && ['input', 'select', 'textarea', 'button'].includes(el.tagName.toLowerCase())) {
            return el.tagName.toLowerCase() + '[name="' + CSS.escape(el.name) + '"]';
        }
        if (el.getAttribute('data-testid')) {
            return '[data-testid="' + CSS.escape(el.getAttribute('data-testid')) + '"]';
        }
        if (el.getAttribute('aria-label')) {
            return el.tagName.toLowerCase() + '[aria-label="' + CSS.escape(el.getAttribute('aria-label')) + '"]';
        }
        
        let path = [];
        let curr = el;
        while (curr && curr.nodeType === Node.ELEMENT_NODE && curr !== document.body && curr !== document.documentElement) {
            let tag = curr.tagName.toLowerCase();
            if (curr.id && !/^[0-9]/.test(curr.id) && !curr.id.includes(' ')) {
                path.unshift('#' + CSS.escape(curr.id));
                break;
            }
            let parent = curr.parentElement;
            if (parent) {
                let siblings = Array.from(parent.children).filter(c => c.tagName.toLowerCase() === tag);
                if (siblings.length > 1) {
                    let index = siblings.indexOf(curr) + 1;
                    path.unshift(tag + ':nth-of-type(' + index + ')');
                } else {
                    path.unshift(tag);
                }
            } else {
                path.unshift(tag);
            }
            curr = parent;
        }
        return path.join(' > ');
    }

    function getXPath(element) {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return '';
        if (element.id && !/^[0-9]/.test(element.id)) {
            return `//*[@id="${element.id}"]`;
        }
        if (element === document.body) return '/html/body';
        let ix = 0;
        let siblings = element.parentNode ? element.parentNode.childNodes : [];
        for (let i = 0; i < siblings.length; i++) {
            let sibling = siblings[i];
            if (sibling === element) {
                let parentXPath = element.parentNode ? getXPath(element.parentNode) : '';
                return parentXPath + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
            }
            if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {
                ix++;
            }
        }
        return '';
    }

    function isVisible(el) {
        if (!el) return false;
        let rect = el.getBoundingClientRect();
        if (rect.width === 0 && rect.height === 0) return false;
        let style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
        return true;
    }

    let interactiveTags = ['a', 'button', 'input', 'select', 'textarea', 'summary', 'option'];
    let interactiveRoles = ['button', 'link', 'textbox', 'checkbox', 'radio', 'combobox', 'menuitem', 'tab', 'switch'];

    let elements = [];
    let seen = new Set();

    function scanTree(root, shadowHost = null) {
        let all = root.querySelectorAll('*');
        for (let el of all) {
            let tag = el.tagName.toLowerCase();
            let role = el.getAttribute('role') || '';
            let isInteractive = interactiveTags.includes(tag) || 
                                interactiveRoles.includes(role) ||
                                el.hasAttribute('onclick') || 
                                el.hasAttribute('tabindex') ||
                                el.getAttribute('contenteditable') === 'true';

            if (isInteractive && !seen.has(el)) {
                seen.add(el);
                let visible = isVisible(el);
                let enabled = !el.hasAttribute('disabled') && !el.getAttribute('aria-disabled');
                let text = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
                if (text.length > 80) text = text.substring(0, 80) + '...';

                let rawValue = el.value !== undefined ? String(el.value) : null;
                if (rawValue && rawValue.length > 50) rawValue = rawValue.substring(0, 50) + '...';

                elements.push({
                    id: el.id || '',
                    tag: tag,
                    type: el.getAttribute('type') || null,
                    name: el.getAttribute('name') || null,
                    role: role || null,
                    text: text || null,
                    placeholder: el.getAttribute('placeholder') || null,
                    value: rawValue,
                    selector: getCssSelector(el),
                    xpath: getXPath(el),
                    visible: visible,
                    enabled: enabled,
                    aria_label: el.getAttribute('aria-label') || null,
                    href: el.getAttribute('href') || null,
                    shadow_host: shadowHost
                });
            }

            // Inspect shadow root if present
            if (el.shadowRoot) {
                let hostSelector = getCssSelector(el);
                scanTree(el.shadowRoot, hostSelector);
            }
        }
    }

    scanTree(document);

    // Focused element selector
    let activeEl = document.activeElement;
    let focusedSelector = (activeEl && activeEl !== document.body) ? getCssSelector(activeEl) : null;

    // Detect iframes
    let iframes = Array.from(document.querySelectorAll('iframe, frame')).map(f => ({
        id: f.id || '',
        name: f.name || '',
        src: f.src || ''
    }));

    return {
        url: window.location.href,
        title: document.title || '',
        focused_element: focusedSelector,
        interactive_elements: elements,
        iframes: iframes
    };
})()"""


def simplify_html(html_str: str, max_chars: int = 25000) -> str:
    """
    Simplify raw HTML into a compact, clean representation:
    - Removes <script>, <style>, <noscript>, <svg> paths, base64 images.
    - Preserves semantic elements, buttons, inputs, links, forms, tables, headings.
    - Truncates oversized attributes while preserving IDs, names, classes, roles, values.
    """
    if not html_str:
        return ""

    # Remove script and style elements completely
    cleaned = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', html_str, flags=re.IGNORECASE)
    cleaned = re.sub(r'<style\b[^<]*(?:(?!<\/style>)<[^<]*)*<\/style>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<noscript\b[^<]*(?:(?!<\/noscript>)<[^<]*)*<\/noscript>', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<!--[\s\S]*?-->', '', cleaned)

    # Strip base64 inline images
    cleaned = re.sub(r'src=["\']data:image/[^"\']+["\']', 'src="[image]"', cleaned, flags=re.IGNORECASE)

    # Truncate or simplify giant inline SVGs
    cleaned = re.sub(r'<svg\b[^>]*>[\s\S]*?<\/svg>', '<svg>[icon]</svg>', cleaned, flags=re.IGNORECASE)

    # Collapse excessive whitespace
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n\s*\n+', '\n', cleaned).strip()

    if len(cleaned) > max_chars:
        return cleaned[:max_chars] + f"\n... [Truncated {len(cleaned) - max_chars} characters]"
    return cleaned


def parse_interactive_elements_from_dict(raw_elements: list[dict[str, Any]]) -> list[InteractiveElement]:
    """Parse raw JS dictionary items into typed InteractiveElement models."""
    parsed: list[InteractiveElement] = []
    for item in raw_elements:
        try:
            parsed.append(
                InteractiveElement(
                    id=item.get("id", ""),
                    tag=item.get("tag", ""),
                    type=item.get("type"),
                    name=item.get("name"),
                    role=item.get("role"),
                    text=item.get("text"),
                    placeholder=item.get("placeholder"),
                    value=item.get("value"),
                    selector=item.get("selector", ""),
                    xpath=item.get("xpath", ""),
                    visible=bool(item.get("visible", True)),
                    enabled=bool(item.get("enabled", True)),
                    aria_label=item.get("aria_label"),
                    href=item.get("href"),
                    frame_id=item.get("frame_id"),
                    shadow_host=item.get("shadow_host"),
                )
            )
        except Exception:
            continue
    return parsed
