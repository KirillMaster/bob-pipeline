namespace Calculator;

public static class Calc
{
    public static int Add(int a, int b) => a + b;

    public static int Divide(int a, int b)
    {
        if (b == 0) throw new DivideByZeroException("b must be non-zero");
        return a / b;
    }

    // Surviving-mutant seed: the boundary (>= vs >) is NOT covered by tests,
    // so Stryker's boundary mutation on this line survives → Hardener has work.
    public static bool IsPositive(int value) => value >= 1;
}
