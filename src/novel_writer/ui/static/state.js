// S1 草稿仅在内存；界面状态不进入小说 revision 或浏览器磁盘存储。
export class DraftStore {
  #items = new Map();
  get size() { return this.#items.size; }
  get(key) { return this.#items.get(key); }
  entries() { return [...this.#items.entries()]; }
  put(key, project, revision, values, position = {}) {
    const previous = this.get(key);
    this.#items.set(key, { project, baseRevision: previous?.baseRevision ?? revision, values: { ...values }, position: { ...position }, local: previous?.local === true, sensitiveFieldsRequired: previous?.sensitiveFieldsRequired === true, updatedAt: new Date().toISOString() });
  }
  restore(key, project, baseRevision, values, position = {}, updatedAt = '', sensitiveFieldsRequired = false) {
    this.#items.set(key, { project, baseRevision, values: { ...values }, position: { ...position }, local: true, sensitiveFieldsRequired: sensitiveFieldsRequired === true, updatedAt });
  }
  remove(key) { this.#items.delete(key); }
  rebase(key, revision) { const draft = this.get(key); if (draft) { draft.baseRevision = revision; draft.updatedAt = new Date().toISOString(); } }
  acknowledge(project, previousRevision, revision, savedKey) {
    if (savedKey) this.remove(savedKey);
    for (const draft of this.#items.values()) {
      if (draft.project === project && draft.baseRevision === previousRevision) draft.baseRevision = revision;
    }
  }
}

// 未发送的需求与上下文引用只在本窗口内存，不是会话历史或生成任务。
export class PromptStore {
  #items = new Map();
  get(project) { return { text: '', chapter: '', character: '', world: false, revision: null, ...this.#items.get(project) }; }
  set(project, value) {
    this.#items.set(project, { text: value.text || '', chapter: value.chapter || '', character: value.character || '', world: value.world === true, revision: value.revision ?? null });
  }
  clear(project) { this.#items.delete(project); }
  get hasText() { return [...this.#items.values()].some(value => value.text.length > 0); }
}

// 超过矩阵预算时以共同首尾 + 中段增删降级，保留全部文本而不阻塞长章。
export function diffLines(before, after) {
  const a = String(before).split('\n'), b = String(after).split('\n');
  let head = 0, tail = 0;
  while (head < a.length && head < b.length && a[head] === b[head]) head++;
  while (tail < a.length - head && tail < b.length - head && a[a.length - 1 - tail] === b[b.length - 1 - tail]) tail++;
  const rows = a.slice(0, head).map(text => ({ kind: 'same', text }));
  const x = a.slice(head, a.length - tail), y = b.slice(head, b.length - tail);
  if (x.length * y.length > 250000) {
    rows.push(...x.map(text => ({ kind: 'remove', text })), ...y.map(text => ({ kind: 'add', text })));
  } else {
    const matrix = Array.from({ length: x.length + 1 }, () => new Uint32Array(y.length + 1));
    for (let i = x.length - 1; i >= 0; i--) for (let j = y.length - 1; j >= 0; j--) {
      matrix[i][j] = x[i] === y[j] ? 1 + matrix[i + 1][j + 1] : Math.max(matrix[i + 1][j], matrix[i][j + 1]);
    }
    let i = 0, j = 0;
    while (i < x.length || j < y.length) {
      if (i < x.length && j < y.length && x[i] === y[j]) { rows.push({ kind: 'same', text: x[i++] }); j++; }
      else if (i < x.length && (j === y.length || matrix[i + 1][j] >= matrix[i][j + 1])) rows.push({ kind: 'remove', text: x[i++] });
      else rows.push({ kind: 'add', text: y[j++] });
    }
  }
  rows.push(...a.slice(a.length - tail).map(text => ({ kind: 'same', text })));
  return rows;
}
