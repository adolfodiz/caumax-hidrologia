<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis styleCategories="AllStyleCategories" hasScaleBasedVisibilityFlag="0" maxScale="0" minScale="1e+08" version="3.8.3-Zanzibar">
  <flags>
    <Identifiable>1</Identifiable>
    <Removable>1</Removable>
    <Searchable>1</Searchable>
  </flags>
  <customproperties>
    <property key="WMSBackgroundLayer" value="false"/>
    <property key="WMSPublishDataSourceUrl" value="false"/>
    <property key="embeddedWidgets/count" value="0"/>
    <property key="identify/format" value="Value"/>
  </customproperties>
  <pipe>
    <rasterrenderer alphaBand="-1" opacity="1" classificationMin="10" classificationMax="inf" band="1" type="singlebandpseudocolor">
      <rasterTransparency/>
      <minMaxOrigin>
        <limits>None</limits>
        <extent>WholeRaster</extent>
        <statAccuracy>Estimated</statAccuracy>
        <cumulativeCutLower>0.02</cumulativeCutLower>
        <cumulativeCutUpper>0.98</cumulativeCutUpper>
        <stdDevFactor>2</stdDevFactor>
      </minMaxOrigin>
      <rastershader>
        <colorrampshader colorRampType="DISCRETE" clip="0" classificationMode="2">
          <colorramp name="[source]" type="gradient">
            <prop v="247,251,255,255" k="color1"/>
            <prop v="8,48,107,255" k="color2"/>
            <prop v="0" k="discrete"/>
            <prop v="gradient" k="rampType"/>
            <prop v="0.13;222,235,247,255:0.26;198,219,239,255:0.39;158,202,225,255:0.52;107,174,214,255:0.65;66,146,198,255:0.78;33,113,181,255:0.9;8,81,156,255" k="stops"/>
          </colorramp>
          <item color="#ecfece" label="0 - 10 m3/s" alpha="255" value="10"/>
          <item color="#ffffe9" label="10 - 25 m3/s" alpha="255" value="25"/>
          <item color="#c4ffc1" label="10  - 50 m3/s" alpha="255" value="50"/>
          <item color="#afda98" label="50 - 100 m3/s" alpha="255" value="100"/>
          <item color="#6fe3a6" label="100 - 200 m3/s" alpha="255" value="200"/>
          <item color="#6ac28e" label="200 - 500 m3/s" alpha="255" value="500"/>
          <item color="#439aab" label="500 - 1000 m3/s" alpha="255" value="1000"/>
          <item color="#1e717c" label="1000 - 2000 m3/s" alpha="255" value="2000"/>
          <item color="#214b79" label="2000 - 3000 m3/s" alpha="255" value="3000"/>
          <item color="#3813a1" label="3000 - 5000 m3/s" alpha="255" value="5000"/>
          <item color="#6e11b3" label="5000 - 7000 m3/s" alpha="255" value="7000"/>
          <item color="#084b94" label="7000 - 10000 m3/s" alpha="255" value="10000"/>
          <item color="#08306b" label="> 10000 m3/s" alpha="255" value="inf"/>
        </colorrampshader>
      </rastershader>
    </rasterrenderer>
    <brightnesscontrast contrast="0" brightness="0"/>
    <huesaturation grayscaleMode="0" colorizeOn="0" colorizeStrength="100" colorizeBlue="128" saturation="0" colorizeRed="255" colorizeGreen="128"/>
    <rasterresampler maxOversampling="2"/>
  </pipe>
  <blendMode>0</blendMode>
</qgis>
