using OxyPlot;

public static class ModelColors
{
    //public static readonly OxyColor Obs = OxyColor.FromRgb(0, 150, 0);      // Grün
    //public static readonly OxyColor Climate = OxyColor.FromRgb(70, 70, 70); // Grau
    //public static readonly OxyColor Mosmix = OxyColor.FromRgb(0, 87, 183);  // Blau
    //public static readonly OxyColor Icon = OxyColor.FromRgb(139, 0, 139);   // Lila
    //public static readonly OxyColor Gfs = OxyColor.FromRgb(215, 118, 32);   // Orange
    //public static readonly OxyColor Ifs = OxyColor.FromRgb(200, 0, 40);     // Rot
    //public static readonly OxyColor UKMO = OxyColor.FromRgb(130, 75, 30);   // Braun
    //public static readonly OxyColor GEM = OxyColor.FromRgb(200,165,0);      // Gold
    //public static readonly OxyColor AIFS = OxyColor.FromRgb(0,160,160);     // Cyan

    public static readonly OxyColor Obs = OxyColor.FromRgb(0, 150, 0);      // Grün (Beobachtungen)
    public static readonly OxyColor Climate = OxyColor.FromRgb(70, 70, 70);     // Grau (Klimamittel)

    // DWD-Familie
    public static readonly OxyColor Mosmix = OxyColor.FromRgb(0, 87, 183);     // Blau
    public static readonly OxyColor Icon = OxyColor.FromRgb(139, 0, 139);    // Lila

    // ECMWF-Familie
    public static readonly OxyColor Ifs = OxyColor.FromRgb(200, 0, 40);     // Rot
    public static readonly OxyColor AIFS = OxyColor.FromRgb(215, 118, 32);   // Orange (ehemals GFS)

    // Nordamerika-Familie
    public static readonly OxyColor Gfs = OxyColor.FromRgb(200, 165, 0);      // Gold (ehemals GEM)
    public static readonly OxyColor GEM = OxyColor.FromRgb(130, 75, 30);    // Braun (ehemals UKMO)

    // Einzelgänger
    public static readonly OxyColor UKMO = OxyColor.FromRgb(0, 160, 160);      // Cyan (ehemals AIFS)


    public static readonly OxyColor MajorGridline = OxyColor.FromRgb(120, 120, 120);
    public static readonly OxyColor MinorGridlineColor = OxyColor.FromRgb(150, 150, 150);
}
