/**
 * Quadlet unit-naming helpers and type conventions.
 */

// Mirrors services/quadlet_naming.py. Podman's generator suffixes
// pod/volume/network/image/build units with their type; container and
// kube units are unsuffixed.
const SUFFIXED_QUADLET_TYPES = new Set(['pod', 'volume', 'network', 'image', 'build']);

export function unitNameFor(fileName) {
    const dotIndex = fileName.lastIndexOf('.');
    if (dotIndex === -1) return fileName + '.service';
    const base = fileName.slice(0, dotIndex);
    const type = fileName.slice(dotIndex + 1).toLowerCase();
    if (SUFFIXED_QUADLET_TYPES.has(type)) return base + '-' + type + '.service';
    return base + '.service';
}

// Podman's generator maps both `my.pod` and `my-pod.container` to the same
// unit name `my-pod.service`, so stripping a `-<type>` suffix by guessing
// from the unit name alone is ambiguous. The caller passes the quadlet type
// it already knows instead, and an absent/unsuffixed type strips nothing
// rather than risking a too-short stem.
export function stemFromUnitName(unitName, quadletType) {
    let result = unitName.endsWith('.service') ? unitName.slice(0, -'.service'.length) : unitName;
    if (quadletType) {
        const type = quadletType.toLowerCase();
        if (SUFFIXED_QUADLET_TYPES.has(type)) {
            const suffix = '-' + type;
            if (result.endsWith(suffix)) {
                result = result.slice(0, -suffix.length);
            }
        }
    }
    return result;
}
