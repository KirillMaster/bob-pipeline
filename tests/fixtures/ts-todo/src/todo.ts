export interface Todo {
  id: number;
  title: string;
  done: boolean;
}

let nextId = 1;
const todos: Todo[] = [];

export function addTodo(title: string): Todo {
  if (title.trim() === "") throw new Error("title must be non-empty");
  const todo = { id: nextId++, title: title.trim(), done: false };
  todos.push(todo);
  return todo;
}

export function completeTodo(id: number): Todo {
  const todo = todos.find((t) => t.id === id);
  if (!todo) throw new Error(`todo ${id} not found`);
  todo.done = true;
  return todo;
}

export function reset(): void {
  todos.length = 0;
  nextId = 1;
}

// Duplication seed: formatOpen/formatDone are copy-pasted twins — jscpd flags
// them, giving Cleaner concrete duplication to remove.
export function formatOpen(list: Todo[]): string {
  const open = list.filter((t) => !t.done);
  const lines: string[] = [];
  for (const t of open) {
    const mark = t.done ? "x" : " ";
    lines.push(`[${mark}] #${t.id} ${t.title}`);
  }
  return lines.join("\n");
}

export function formatDone(list: Todo[]): string {
  const done = list.filter((t) => t.done);
  const lines: string[] = [];
  for (const t of done) {
    const mark = t.done ? "x" : " ";
    lines.push(`[${mark}] #${t.id} ${t.title}`);
  }
  return lines.join("\n");
}

export function allTodos(): Todo[] {
  return [...todos];
}
