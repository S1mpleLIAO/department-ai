export let state = {
  processes: [], categories: [], purposes: [], documents: [],
  skills: [], settings: null, services: {},
}

export function replaceState(value) { state = value }
