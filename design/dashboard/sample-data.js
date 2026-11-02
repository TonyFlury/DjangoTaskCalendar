/* Pure sample data for the unchanged dashboard renderer. No API calls or database access. */
(() => {
    const days=72;
    function metric(id,label,total,finalAverage,finalMaximum,comparableAverage,colour,description,unit='',precision=0) {
        const round=n=>precision?Math.round(n*100)/100:Math.round(n);
        const cumulative=Array.from({length:days+1},(_,day)=>({day,current:round(total*Math.pow(day/days,1.55)),average:round(comparableAverage*Math.pow(day/days,1.45)),maximum:round(comparableAverage*1.2*Math.pow(day/days,1.35))}));
        const weekly=[{day:0,fromDay:null,current:0,average:0,maximum:0,partial:false}];
        for(let day=7;day<=days+6;day+=7){const end=Math.min(day,days),from=day-7;weekly.push({day:end,fromDay:from,current:round(cumulative[end].current-cumulative[from].current),average:round(cumulative[end].average-cumulative[from].average),maximum:round(cumulative[end].maximum-cumulative[from].maximum),partial:end!==day});if(end===days)break;}
        return {id,label,total,finalAverage,finalMaximum,comparableAverage,colour,description,unit,precision,days,start:'2027-04-01',countLabel:unit?'confirmed cash':'locations',differencePercent:(total/comparableAverage-1)*100,finalSample:4,comparableSample:4,warnings:[],historicalWarnings:[],cumulative,weekly};
    }
    const cash=metric('cash','Cash contributions',4650,6400,8200,3950,'#2164b0','Sample confirmed cash contributions.','£',2);
    const gifts=metric('noncash','Non-cash contributions',24,30,36,22,'#ae5c10','Sample non-cash contributions.');gifts.countLabel='confirmed gifts';
    const boards=metric('boards','Ad-board locations',61,70,82,58,'#8152af','Sample active advertising board locations.');
    const sales=metric('sales','Sales locations',132,166,194,116,'#167768','Sample active sale locations.');
    const invited=metric('market_invited','Invited',18,15,20,11,'#2164b0','');
    const accepted=metric('market_accepted','Accepted',12,15,20,11,'#a16207','');
    const paid=metric('market_paid','Fees paid',9,15,20,11,'#15803d','');
    const market={...accepted,id:'market',label:'Craft Market',kind:'pipeline',countLabel:'confirmed places',description:'Sample invitation, acceptance and paid-fee counts.',stages:[invited,accepted,paid]};
    document.getElementById('event-dashboard-data').textContent=JSON.stringify({metrics:[cash,gifts,boards,sales,market],timeline:null,previousEvents:4});
})();
