/*
 * PROJECT:     ReactOS Testman
 * LICENSE:     GPL-2.0+ (https://spdx.org/licenses/GPL-2.0+)
 * PURPOSE:     JavaScript file for the Testman Front Page
 * COPYRIGHT:   Copyright 2008-2017 Colin Finck (colin@reactos.org)
 *              Copyright 2014 Kamil Hornicek (kamil.hornicek@reactos.org)
 *              Copyright 2026 ReactOS Contributors
 */

var CurrentPage;
var data;
var RevisionRangeStart;
var RevisionRangeEnd;
var PageCount;
var ResultCount;
var SelectedResults = new Object();
var SelectedResultCount = 0;

var REQUESTTYPE_FULLLOAD = 1;
var REQUESTTYPE_ADDPAGE = 2;
var REQUESTTYPE_PAGESWITCH = 3;

function SetLoading(value)
{
	document.getElementById("ajax_loading_search").style.visibility = (value ? "visible" : "hidden");
}

function UpdateAllCheckboxes()
{
	for (id in SelectedResults)
	{
		var checkbox = document.getElementById("test_" + id);

		if (checkbox)
			checkbox.checked = true;
	}
}

function ResultCheckbox_OnClick(checkbox)
{
	if (checkbox.checked && SelectedResultCount == MAX_COMPARE_RESULTS)
	{
		alert(testman_langres["maxselection"].replace(/\{1\}/, MAX_COMPARE_RESULTS));
		checkbox.checked = false;
		return;
	}

	var id = checkbox.id.substr(5);

	if (checkbox.checked)
	{
		SelectedResults[id] = true;
		SelectedResultCount++;
	}
	else
	{
		delete SelectedResults[id];
		SelectedResultCount--;
	}

	document.getElementById("selectedresultcount").innerHTML = SelectedResultCount;
}

function ResultCell_OnClick(elem)
{
	var IDArray = new Array();
	IDArray.push(parseInt(elem.parentNode.firstChild.firstChild.id.substr(5)));
	OpenComparePage(IDArray);
}

function GetRevisions()
{
	var revisions = document.getElementById("search_revision").value;

	if (!revisions)
	{
		RevisionRangeStart = "";
		RevisionRangeEnd = "";
		return true;
	}

	var hyphen = revisions.indexOf("-");
	if (hyphen > 0)
	{
		RevisionRangeStart = revisions.substr(0, hyphen);
		RevisionRangeEnd = revisions.substr(hyphen + 1);
	}
	else
	{
		RevisionRangeStart = revisions;
		RevisionRangeEnd = revisions;
	}

	return (RevisionRangeStart && RevisionRangeEnd);
}

/**
 * Append search filter GET parameters (sources, date range, comment, build number, facet dimensions).
 */
function ApplySearchFiltersToData(d)
{
	var allSrc = document.querySelectorAll(".source_filter_cb");
	var chkSrc = document.querySelectorAll(".source_filter_cb:checked");
	if (allSrc.length && chkSrc.length === 0)
		throw new Error("nosources");
	if (chkSrc.length > 0 && chkSrc.length < allSrc.length)
	{
		var ids = [];
		for (var i = 0; i < chkSrc.length; i++)
			ids.push(chkSrc[i].value);
		d["source_ids"] = ids.join(",");
	}

	var df = document.getElementById("search_date_from").value.replace(/^\s+|\s+$/g, "");
	if (df)
		d["date_from"] = df;
	var dt = document.getElementById("search_date_to").value.replace(/^\s+|\s+$/g, "");
	if (dt)
		d["date_to"] = dt;
	var sc = document.getElementById("search_comment").value.replace(/^\s+|\s+$/g, "");
	if (sc)
		d["search_comment"] = sc;
	var bn = document.getElementById("search_build_number").value.replace(/^\s+|\s+$/g, "");
	if (bn)
		d["build_number"] = bn;

	function addFacet(boxName, param)
	{
		// Must use getElementsByName: names like fac_arch[] break querySelectorAll because `]`
		// ends the CSS [attr="..."] selector, so no inputs match and filters are never sent.
		var all = document.getElementsByName(boxName);
		if (!all || !all.length)
			return;
		var on = [];
		for (var i = 0; i < all.length; i++)
		{
			if (all[i].checked)
				on.push(all[i]);
		}
		if (!on.length)
		{
			// Do not send an empty query value: PHP treats compilers= etc. as "" and applies 0=1 (no rows).
			return;
		}
		if (on.length < all.length)
		{
			var v = [];
			for (var j = 0; j < on.length; j++)
				v.push(on[j].value);
			d[param] = v.join(",");
		}
	}

	addFacet("fac_compiler[]", "compilers");
	addFacet("fac_vm[]", "vms");
	addFacet("fac_host_os[]", "host_oses");
	addFacet("fac_arch[]", "arches");
}

function SearchCall()
{
	SetLoading(true);
	AjaxGet("ajax-search.php", "SearchCallback", data);
}

function SearchButton_OnClick()
{
	if (!GetRevisions())
	{
		alert(shared_langres["invalidrev"]);
		return;
	}

	CurrentPage = 1;
	data = new Array();
	data["startrev"] = RevisionRangeStart;
	data["endrev"] = RevisionRangeEnd;
	data["page"] = CurrentPage;
	data["resultlist"] = 1;
	data["requesttype"] = REQUESTTYPE_FULLLOAD;

	try
	{
		ApplySearchFiltersToData(data);
	}
	catch (e)
	{
		if (e.message === "nosources")
		{
			alert(testman_langres["nosources"]);
			return;
		}
		throw e;
	}

	SearchCall();
}

function ResizeIFrame()
{
	var iframe = document.getElementById("comparepage_frame");
	iframe.height = iframe.contentDocument.body.offsetHeight + 40;
}

function Load()
{
	var f = function(keyevent)
	{
		if ((keyevent && keyevent.which == 13) || (window.event && window.event.keyCode == 13))
			SearchButton_OnClick();
	};
	document.getElementById("search_revision").onkeypress = f;
	document.getElementById("search_date_from").onkeypress = f;
	document.getElementById("search_date_to").onkeypress = f;
	document.getElementById("search_comment").onkeypress = f;
	document.getElementById("search_build_number").onkeypress = f;

	if (window.localStorage)
		document.getElementById("opennewwindow").checked = parseInt(window.localStorage.getItem("testman_opennewwindow"));

	CurrentPage = 1;
	data = new Array();
	data["desc"] = 1;
	data["limit"] = DEFAULT_SEARCH_LIMIT;
	data["page"] = CurrentPage;
	data["resultlist"] = 1;
	data["requesttype"] = REQUESTTYPE_FULLLOAD;

	try
	{
		ApplySearchFiltersToData(data);
	}
	catch (e)
	{
	}

	SearchCall();
}

function GetTagData(RootElement, TagName)
{
	var Child = RootElement.getElementsByTagName(TagName)[0].firstChild;
	return Child ? Child.data : "";
}

function GetTagDataSafe(RootElement, TagName, defaultVal)
{
	var els = RootElement.getElementsByTagName(TagName);
	if (!els.length || !els[0].firstChild)
		return defaultVal;
	return els[0].firstChild.data;
}

function SearchCallback(HttpRequest)
{
	if (HttpRequest.responseXML.getElementsByTagName("error").length > 0)
	{
		alert(HttpRequest.responseXML.getElementsByTagName("error")[0].firstChild.data)
		return;
	}

	var html = "";
	var RequestResultCount = parseInt(HttpRequest.responseXML.getElementsByTagName("resultcount")[0].firstChild.data);
	var MoreResults = (RequestResultCount > RESULTS_PER_PAGE);
	var FirstRev = "";
	var LastRev = "";

	if (RequestResultCount > 0)
	{
		FirstRev = HttpRequest.responseXML.getElementsByTagName("firstrev")[0].firstChild.data;
		LastRev = HttpRequest.responseXML.getElementsByTagName("lastrev")[0].firstChild.data;
	}

	if (data["requesttype"] == REQUESTTYPE_FULLLOAD || data["requesttype"] == REQUESTTYPE_PAGESWITCH)
	{
		html += '<div class="row"><div id="infobox" class="col-sm-2">';

		if (data["requesttype"] == REQUESTTYPE_FULLLOAD)
		{
			ResultCount = RequestResultCount;
			PageCount = 1;
			html += testman_langres["foundresults"].replace(/\{1\}/, ResultCount);
		}
		else
		{
			html += document.getElementById("infobox").innerHTML;
		}

		html += '<\/div>';

		html += '<div class="col-sm-4">';
		html += testman_langres["status"].replace(/\{1\}/, '<span id="selectedresultcount">' + SelectedResultCount + '<\/span>');
		html += ' <button class="btn btn-default" onclick="ClearSelected_OnClick()">' + testman_langres["clearselected"] + '<\/button>';
		html += '<\/div>';

		if (PageCount > 1 || MoreResults)
		{
			html += '<div id="pagesbox" class="form-inline pull-right">';

			html += '<button class="btn btn-default" ' + (CurrentPage > 1 ? 'onclick="FirstPage_OnClick()"' : 'disabled="disabled"') + ' title="' + shared_langres["firstpage_title"] + '"><i class="fa fa-angle-double-left"><\/i><\/button> ';
			html += '<button class="btn btn-default" ' + (CurrentPage > 1 ? 'onclick="PrevPage_OnClick()"' : 'disabled="disabled"') + ' title="' + shared_langres["prevpage_title"] + '"><i class="fa fa-angle-left"><\/i><\/button> ';

			html += '<select class="form-control" id="pagesel" size="1" onchange="PageBox_OnChange(this)">';

			if (data["requesttype"] == REQUESTTYPE_FULLLOAD)
			{
				html += '<option value="' + CurrentPage + '">';
				html += shared_langres["page"] + ' ' + CurrentPage;
				html += ' - ' + FirstRev + ' ... ' + LastRev;
				html += '<\/option>';
			}
			else
			{
				html += document.getElementById("pagesel").innerHTML;
			}

			html += '<\/select> ';

			html += '<button class="btn btn-default" ' + (MoreResults ? 'onclick="NextPage_OnClick()"' : 'disabled="disabled"') + ' title="' + shared_langres["nextpage_title"] + '"><i class="fa fa-angle-right"><\/i><\/button> ';
			html += '<button class="btn btn-default" ' + (MoreResults ? 'onclick="LastPage_OnClick()"' : 'disabled="disabled"') + ' title="' + shared_langres["lastpage_title"] + '"><i class="fa fa-angle-double-right"><\/i><\/button>';

			html += '<\/div>';
		}

		html += '<\/div><\/div>';

		html += '<table class="table table-hover" id="resulttable">';

		html += '<thead><tr class="head">';
		html += '<th class="TestCheckbox"><\/th>';
		html += '<th>' + shared_langres["revision"] + '<\/th>';
		html += '<th>' + shared_langres["date"] + '<\/th>';
		html += '<th>' + testman_langres["totaltests"] + '<\/th>';
		html += '<th>' + testman_langres["failedtests"] + '<\/th>';
		html += '<th>' + testman_langres["todotests"] + '<\/th>';
		html += '<th>' + testman_langres["source"] + '<\/th>';
		html += '<th>' + testman_langres["platform"] + '<\/th>';
		html += '<th>' + testman_langres["comment"] + '<\/th>';
		html += '<\/tr><\/thead>';
		html += '<tbody>';

		var results = HttpRequest.responseXML.getElementsByTagName("result");

		if (!results.length)
		{
			html += '<tr><td colspan="9">' + testman_langres["noresults"] + '<\/td><\/tr>';
		}
		else
		{
			for (var i = 0; i < results.length; i++)
			{
				html += '<tr>';
				html += '<td><input onclick="ResultCheckbox_OnClick(this)" type="checkbox" id="test_' + GetTagData(results[i], "id") + '" \/><\/td>';
				html += '<td onclick="ResultCell_OnClick(this)">' + GetTagData(results[i], "revision") + '<\/td>';
				html += '<td onclick="ResultCell_OnClick(this)">' + GetTagData(results[i], "date") + '<\/td>';
				html += '<td onclick="ResultCell_OnClick(this)">' + GetTagData(results[i], "count") + '<\/td>';
				html += '<td onclick="ResultCell_OnClick(this)">' + GetTagData(results[i], "failures") + '<\/td>';
				html += '<td onclick="ResultCell_OnClick(this)">' + GetTagDataSafe(results[i], "todo", "0") + '<\/td>';
				html += '<td onclick="ResultCell_OnClick(this)">' + GetTagData(results[i], "source") + '<\/td>';
				html += '<td onclick="ResultCell_OnClick(this)">' + GetTagData(results[i], "platform") + '<\/td>';
				html += '<td onclick="ResultCell_OnClick(this)">' + GetTagData(results[i], "comment") + '<\/td>';
				html += '<\/tr>';
			}
		}

		html += '<\/tbody><\/table>';

		document.getElementById("searchtable").innerHTML = html;

		if (data["requesttype"] == REQUESTTYPE_PAGESWITCH)
		{
			document.getElementById("pagesel").getElementsByTagName("option")[CurrentPage - 1].selected = true;
		}

		UpdateAllCheckboxes();
	}
	else
	{
		PageCount++;

		var OptionElem = document.createElement("option");
		var OptionText = document.createTextNode(shared_langres["page"] + ' ' + PageCount + ' - ' + FirstRev + ' ... ' + LastRev);

		OptionElem.value = PageCount;
		OptionElem.appendChild(OptionText);

		document.getElementById("pagesel").appendChild(OptionElem);
	}

	if (MoreResults && (data["requesttype"] == REQUESTTYPE_FULLLOAD || data["requesttype"] == REQUESTTYPE_ADDPAGE))
	{
		data["resultlist"] = 0;
		data["page"] = PageCount + 1;
		data["requesttype"] = REQUESTTYPE_ADDPAGE;
		SearchCall();
	}
	else
	{
		// Do not auto-fill revision: that pins the next search to the first page's rev span and
		// hides other arches / builders (e.g. amd64 KVM outside that range).

		SetLoading(false);
	}
}

function OpenComparePage(ResultArray)
{
	var parameters = "ids=";

	ResultArray.sort(NumericComparison);

	for (var i = 0; i < ResultArray.length; i++)
	{
		if (i == 0)
		{
			parameters += ResultArray[i];
			continue;
		}

		parameters += "," + ResultArray[i];
	}

	if (document.getElementById("opennewwindow").checked)
	{
		window.open("compare.php?" + parameters);
	}
	else
	{
		var iframe = document.getElementById("comparepage_frame");

		iframe.src = "compare.php?" + parameters;
		iframe.style.display = "block";
	}
}

function CompareFirstTwoButton_OnClick()
{
	var IDArray;
	var trs = document.getElementById("resulttable").getElementsByTagName("tbody")[0].getElementsByTagName("tr");

	if (trs[0].firstChild.firstChild.nodeName != "INPUT")
		return;

	IDArray = new Array();
	IDArray.push(parseInt(trs[0].firstChild.firstChild.id.substr(5)));

	if (trs[1])
		IDArray.push(parseInt(trs[1].firstChild.firstChild.id.substr(5)));

	OpenComparePage(IDArray);
}

function PageSwitch(NewPage)
{
	CurrentPage = NewPage;
	data["page"] = NewPage;
	data["resultlist"] = 1;
	data["requesttype"] = REQUESTTYPE_PAGESWITCH;

	try
	{
		ApplySearchFiltersToData(data);
	}
	catch (e)
	{
	}

	SearchCall();
}

function FirstPage_OnClick()
{
	PageSwitch(document.getElementById("pagesel").getElementsByTagName("option")[0].value);
}

function PrevPage_OnClick()
{
	PageSwitch(document.getElementById("pagesel").getElementsByTagName("option")[CurrentPage - 2].value);
}

function PageBox_OnChange(elem)
{
	PageSwitch(elem.value);
}

function NextPage_OnClick()
{
	PageSwitch(document.getElementById("pagesel").getElementsByTagName("option")[CurrentPage].value);
}

function LastPage_OnClick()
{
	PageSwitch(document.getElementById("pagesel").getElementsByTagName("option")[PageCount - 1].value);
}

function NumericComparison(a, b)
{
	return a - b;
}

function CompareSelectedButton_OnClick()
{
	var IDArray = new Array();

	for (id in SelectedResults)
		IDArray.push(parseInt(id));

	if (!IDArray.length)
	{
		alert(testman_langres["noselection"]);
		return;
	}
	else if (IDArray.length < 2)
	{
		alert(testman_langres["selectatleast"].replace(/\{1\}/, 2));
		return;
	}

	OpenComparePage(IDArray);
}

function OpenNewWindowCheckbox_OnClick(checkbox)
{
	if (window.localStorage)
		window.localStorage.setItem("testman_opennewwindow", checkbox.checked ? '1' : '0');

	document.getElementById("comparepage_frame").style.display = "none";
}

function ClearSelected_OnClick()
{
	document.getElementById("selectedresultcount").innerHTML = '0';

	for (id in SelectedResults)
		document.getElementById('test_' + id).checked = false;

	SelectedResults = new Object();
	SelectedResultCount = 0;
}
