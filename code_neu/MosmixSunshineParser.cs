using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net.Http;
using System.Xml.Linq;
using static MosmixParser;

public class MosmixSunshineParser
{
    private const string MosmixLatestUrl =
        "https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/all_stations/kml/MOSMIX_L_LATEST.kmz";

    public class StationSunshine
    {
        public string StationId { get; set; }
        public double Latitude { get; set; }
        public double Longitude { get; set; }

        // Sonnenscheindauer pro Zeitschritt (Sekunden)
        public Dictionary<DateTime, double> SunshineSecondsPerHour { get; set; } = new();

        // Niederschlag pro Zeitschritt (mm, RR1c)
        public Dictionary<DateTime, double> RainMmPerHour { get; set; } = new();

        // Temperatur pro Zeitschritt (°C, aus TTT)
        public Dictionary<DateTime, double> TempCPerHour { get; set; } = new();
    }

    /// <summary>
    /// Lädt MOSMIX_L_LATEST.kmz vom DWD, parst SunD1, RR1c und TTT und liefert alle Stationen.
    /// </summary>
    public List<StationSunshine> ParseLatestFromDwd()
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mosmix_" + Guid.NewGuid());
        Directory.CreateDirectory(tempDir);

        string kmzPath = Path.Combine(tempDir, "MOSMIX_L_LATEST.kmz");

        using (var http = new HttpClient())
        {
            var bytes = http.GetByteArrayAsync(MosmixLatestUrl).Result;
            File.WriteAllBytes(kmzPath, bytes);
        }

        return ParseKmz(kmzPath);
    }

    public List<StationSunshine> ParseKmz(string kmzPath)
    {
        string tempDir = Path.Combine(Path.GetTempPath(), "mosmix_" + Guid.NewGuid());
        Directory.CreateDirectory(tempDir);

        // KMZ entpacken
        ZipFile.ExtractToDirectory(kmzPath, tempDir);

        // KML finden
        string kmlPath = Directory.GetFiles(tempDir, "*.kml", SearchOption.AllDirectories).First();

        XDocument doc = XDocument.Load(kmlPath);

        XNamespace kml = "http://www.opengis.net/kml/2.2";
        XNamespace dwd = "https://opendata.dwd.de/weather/lib/pointforecast_dwd_extension_V1_0.xsd";

        // Zeitstempel auslesen
        var timeSteps = doc.Descendants(dwd + "TimeStep")
                           .Select(x => DateTime.Parse(x.Value, null, DateTimeStyles.AdjustToUniversal))
                           .ToList();

        var stations = new List<StationSunshine>();

        foreach (var placemark in doc.Descendants(kml + "Placemark"))
        {
            var id = placemark.Element(kml + "name")?.Value?.Trim();
            var desc = placemark.Element(kml + "description")?.Value?.Trim();
            if (string.IsNullOrEmpty(id))
                continue;

            // Koordinaten
            var coordText = placemark.Descendants(kml + "coordinates").First().Value.Trim();
            var parts = coordText.Split(',');
            double lon = double.Parse(parts[0], CultureInfo.InvariantCulture);
            double lat = double.Parse(parts[1], CultureInfo.InvariantCulture);

            var station = new StationData
            {
                StationId = id,
                Name = string.IsNullOrWhiteSpace(desc) ? id : desc,
                Latitude = lat,
                Longitude = lon
            };

            // SunD1 finden (Sonnenscheindauer pro Stunde in Sekunden)
            var sunD1Node = placemark.Descendants(dwd + "Forecast")
                                     .FirstOrDefault(x => x.Attribute(dwd + "elementName")?.Value == "SunD1");

            if (sunD1Node != null)
            {
                var values = sunD1Node.Element(dwd + "value")?.Value?
                    .Split(' ', StringSplitOptions.RemoveEmptyEntries)
                    .Select(v => double.TryParse(v, NumberStyles.Any, CultureInfo.InvariantCulture, out var d) ? d : 0)
                    .ToList();

                if (values != null && values.Count == timeSteps.Count)
                {
                    for (int i = 0; i < timeSteps.Count; i++)
                        station.SunshineSecondsPerHour[timeSteps[i]] = values[i];
                }
            }

            // RR1c finden (Niederschlag pro Stunde in mm)
            var rr1cNode = placemark.Descendants(dwd + "Forecast")
                                    .FirstOrDefault(x => x.Attribute(dwd + "elementName")?.Value == "RR1c");

            if (rr1cNode != null)
            {
                var values = rr1cNode.Element(dwd + "value")?.Value?
                    .Split(' ', StringSplitOptions.RemoveEmptyEntries)
                    .Select(v => double.TryParse(v, NumberStyles.Any, CultureInfo.InvariantCulture, out var d) ? d : 0)
                    .ToList();

                if (values != null && values.Count == timeSteps.Count)
                {
                    for (int i = 0; i < timeSteps.Count; i++)
                        station.RainMmPerHour[timeSteps[i]] = values[i];
                }
            }

            // TTT finden (Temperatur pro Stunde in Kelvin → °C)
            var tttNode = placemark.Descendants(dwd + "Forecast")
                                   .FirstOrDefault(x => x.Attribute(dwd + "elementName")?.Value == "TTT");

            if (tttNode != null)
            {
                var values = tttNode.Element(dwd + "value")?.Value?
                    .Split(' ', StringSplitOptions.RemoveEmptyEntries)
                    .Select(v => double.TryParse(v, NumberStyles.Any, CultureInfo.InvariantCulture, out var d)
                                 ? d - 273.15   // Kelvin → °C
                                 : 0)
                    .ToList();

                if (values != null && values.Count == timeSteps.Count)
                {
                    for (int i = 0; i < timeSteps.Count; i++)
                        station.TempCPerHour[timeSteps[i]] = values[i];
                }
            }

            //stations.Add(station);
        }

        return stations;
    }

    public Dictionary<DateTime, double> ComputeGermanyDailyMean(List<StationSunshine> stations)
    {
        double minLat = 47.0, maxLat = 55.2;
        double minLon = 5.5, maxLon = 15.5;

        var germanStations = stations
            .Where(s => s.Latitude >= minLat && s.Latitude <= maxLat &&
                        s.Longitude >= minLon && s.Longitude <= maxLon)
            .ToList();

        // Tages-Summen pro Station (Sonne)
        var stationDaily = new Dictionary<string, Dictionary<DateTime, double>>();

        foreach (var st in germanStations)
        {
            var daily = new Dictionary<DateTime, double>();

            foreach (var kv in st.SunshineSecondsPerHour)
            {
                var day = kv.Key.Date;

                if (!daily.ContainsKey(day))
                    daily[day] = 0;

                daily[day] += kv.Value; // Sekunden addieren
            }

            stationDaily[st.StationId] = daily;
        }

        // Deutschland-Mittel pro Tag (Sonne)
        var result = new Dictionary<DateTime, double>();

        foreach (var day in stationDaily.SelectMany(s => s.Value.Keys).Distinct())
        {
            var values = stationDaily
                .Where(s => s.Value.ContainsKey(day))
                .Select(s => s.Value[day])
                .ToList();

            result[day] = values.Average() / 3600.0; // Sekunden → Stunden
        }

        return result;
    }

    public Dictionary<DateTime, double> ComputeGermanyDailyRainMean(List<StationSunshine> stations)
    {
        double minLat = 47.0, maxLat = 55.2;
        double minLon = 5.5, maxLon = 15.5;

        var germanStations = stations
            .Where(s => s.Latitude >= minLat && s.Latitude <= maxLat &&
                        s.Longitude >= minLon && s.Longitude <= maxLon)
            .ToList();

        // Tages-Summen pro Station (Regen)
        var stationDaily = new Dictionary<string, Dictionary<DateTime, double>>();

        foreach (var st in germanStations)
        {
            var daily = new Dictionary<DateTime, double>();

            foreach (var kv in st.RainMmPerHour)
            {
                var day = kv.Key.Date;

                if (!daily.ContainsKey(day))
                    daily[day] = 0;

                daily[day] += kv.Value; // mm addieren
            }

            stationDaily[st.StationId] = daily;
        }

        // Deutschland-Mittel pro Tag (Regen, mm)
        var result = new Dictionary<DateTime, double>();

        foreach (var day in stationDaily.SelectMany(s => s.Value.Keys).Distinct())
        {
            var values = stationDaily
                .Where(s => s.Value.ContainsKey(day))
                .Select(s => s.Value[day])
                .ToList();

            result[day] = values.Average(); // mm
        }

        return result;
    }

    public Dictionary<DateTime, double> ComputeGermanyDailyTempMean(List<StationSunshine> stations)
    {
        double minLat = 47.0, maxLat = 55.2;
        double minLon = 5.5, maxLon = 15.5;

        var germanStations = stations
            .Where(s => s.Latitude >= minLat && s.Latitude <= maxLat &&
                        s.Longitude >= minLon && s.Longitude <= maxLon)
            .ToList();

        // Tagesmittel pro Station (Temperatur)
        var stationDaily = new Dictionary<string, Dictionary<DateTime, double>>();

        foreach (var st in germanStations)
        {
            var dailyLists = new Dictionary<DateTime, List<double>>();

            foreach (var kv in st.TempCPerHour)
            {
                var day = kv.Key.Date;

                if (!dailyLists.ContainsKey(day))
                    dailyLists[day] = new List<double>();

                dailyLists[day].Add(kv.Value);
            }

            var dailyMeans = new Dictionary<DateTime, double>();
            foreach (var kv in dailyLists)
                dailyMeans[kv.Key] = kv.Value.Average();

            stationDaily[st.StationId] = dailyMeans;
        }

        // Deutschland-Mittel pro Tag (Temperatur, °C)
        var result = new Dictionary<DateTime, double>();

        foreach (var day in stationDaily.SelectMany(s => s.Value.Keys).Distinct())
        {
            var values = stationDaily
                .Where(s => s.Value.ContainsKey(day))
                .Select(s => s.Value[day])
                .ToList();

            if (values.Count > 0)
                result[day] = values.Average();
        }

        return result;
    }
}
