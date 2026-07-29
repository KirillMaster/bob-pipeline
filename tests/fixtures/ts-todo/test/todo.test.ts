import { beforeEach, describe, expect, it } from "vitest";
import { addTodo, allTodos, completeTodo, formatDone, formatOpen, reset } from "../src/todo";

beforeEach(() => reset());

describe("@S1-AS1 adding a todo", () => {
  it("stores a trimmed, open todo", () => {
    const t = addTodo("  buy milk ");
    expect(t).toMatchObject({ id: 1, title: "buy milk", done: false });
    expect(allTodos()).toHaveLength(1);
  });

  it("rejects an empty title", () => {
    expect(() => addTodo("   ")).toThrow("non-empty");
  });
});

describe("@S1-AS2 completing a todo", () => {
  it("marks the todo done", () => {
    const t = addTodo("task");
    expect(completeTodo(t.id).done).toBe(true);
  });

  it("throws for unknown id", () => {
    expect(() => completeTodo(99)).toThrow("not found");
  });
});

describe("@S1-AS3 formatting", () => {
  it("splits open and done lists", () => {
    addTodo("a");
    const b = addTodo("b");
    completeTodo(b.id);
    expect(formatOpen(allTodos())).toBe("[ ] #1 a");
    expect(formatDone(allTodos())).toBe("[x] #2 b");
  });
});
