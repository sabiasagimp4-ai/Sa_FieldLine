// Compile-check stub of the YMM4 control attributes. Signatures copied from the
// official plugin samples; nothing here runs.
namespace YukkuriMovieMaker.Controls;

[AttributeUsage(AttributeTargets.Property)]
public class AnimationSliderAttribute : Attribute
{
    public AnimationSliderAttribute(string format = "F1", string unit = "", double min = 0, double max = 100) { }
}

[AttributeUsage(AttributeTargets.Property)]
public class TextBoxSliderAttribute : Attribute
{
    public TextBoxSliderAttribute(string format = "F1", string unit = "", double min = 0, double max = 100) { }
}
