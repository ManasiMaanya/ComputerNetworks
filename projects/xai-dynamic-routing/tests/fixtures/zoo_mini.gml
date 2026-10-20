graph [
  DateObtained "1/01/11"
  GeoLocation "Europe"
  Network "ZooMini"
  multigraph 1
  node [
    id 0
    label "Paris"
    Country "France"
    Longitude 2.35
    Internal 1
    Latitude 48.86
  ]
  node [
    id 1
    label "London"
    Country "United Kingdom"
    Longitude -0.13
    Internal 1
    Latitude 51.51
  ]
  node [
    id 2
    label "Berlin"
    Country "Germany"
    Longitude 13.40
    Internal 1
    Latitude 52.52
  ]
  node [
    id 3
    label "Nowhere"
    Internal 1
  ]
  node [
    id 4
    label "Island"
    Longitude 0.0
    Internal 1
    Latitude 0.0
  ]
  node [
    id 5
    label "Paris"
    Country "France"
    Longitude 2.0
    Internal 1
    Latitude 48.0
  ]
  edge [
    source 0
    target 1
    LinkSpeed "10"
    LinkLabel "10G"
    LinkSpeedUnits "G"
    LinkSpeedRaw 10000000000.0
  ]
  edge [
    source 0
    target 1
    LinkSpeedRaw 1000000000.0
  ]
  edge [
    source 1
    target 2
    LinkLabel "2.5 Gbps"
  ]
  edge [
    source 2
    target 3
  ]
  edge [
    source 0
    target 5
    LinkLabel "OC-48"
  ]
  edge [
    source 5
    target 3
    LinkSpeed "100"
    LinkSpeedUnits "M"
  ]
]
