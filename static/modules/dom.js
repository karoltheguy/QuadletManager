/**
 * DOM helpers with no dependency on any other application module.
 */

export function el(tag, attrs, children) {
    const element = document.createElement(tag);
    if (attrs) {
        Object.keys(attrs).forEach(function(k) {
            const val = Reflect.get(attrs, k);
            if (k === 'className') {
                element.className = val;
            } else if (k === 'style' && typeof val === 'object') {
                Object.keys(val).forEach(function(sk) {
                    Reflect.set(element.style, sk, Reflect.get(val, sk));
                });
            } else {
                element.setAttribute(k, val);
            }
        });
    }
    if (children !== undefined && children !== null) {
        if (Array.isArray(children)) {
            children.forEach(function(child) {
                if (typeof child === 'string') {
                    element.appendChild(document.createTextNode(child));
                } else if (child) {
                    element.appendChild(child);
                }
            });
        } else if (typeof children === 'string') {
            element.textContent = children;
        } else {
            element.appendChild(children);
        }
    }
    return element;
}

export function sendNotification(title, body) {
    if ('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, { body: body });
    }
}

export function getRelativeTime(timestamp) {
    const now = Math.floor(Date.now() / 1000);
    const diff = now - timestamp;

    if (diff < 60) return 'just now';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

export function setStatText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}
