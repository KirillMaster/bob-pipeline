using Xunit;

namespace Calculator.Tests;

public class CalcTests
{
    [Fact]
    [Trait("scenario", "S1-AS1")]
    public void Add_TwoNumbers_ReturnsSum() => Assert.Equal(5, Calc.Add(2, 3));

    [Fact]
    [Trait("scenario", "S1-AS2")]
    public void Divide_ByZero_Throws() => Assert.Throws<DivideByZeroException>(() => Calc.Divide(1, 0));

    [Fact]
    [Trait("scenario", "S1-AS3")]
    public void IsPositive_Five_True() => Assert.True(Calc.IsPositive(5));
    // No test at the 0/1 boundary → boundary mutant on IsPositive survives.
}
