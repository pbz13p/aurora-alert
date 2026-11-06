import urllib.request
for u in ["json/planetary_k_index_1m.json","products/noaa-planetary-k-index-forecast.json",
          "products/solar-wind/mag-5-minute.json","products/solar-wind/plasma-5-minute.json",
          "json/rtsw/rtsw_mag_1m.json","json/rtsw/rtsw_wind_1m.json","products/noaa-planetary-k-index.json",
          "products/solar-wind/mag-1-day.json","products/solar-wind/plasma-1-day.json"]:
    url="https://services.swpc.noaa.gov/"+u
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"aurora-alert/1.0"}),timeout=30) as r:
            b=r.read().decode()
            print("OK ",u,len(b),b[:300].replace("\n"," "))
    except Exception as e:
        print("ERR",u,e)
